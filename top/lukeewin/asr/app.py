# !/usr/bin/env python
# _*_ coding utf-8 _*_
# @Time: 2026/1/8 18:08
# @Author: Luke Ewin
# @Blog: https://blog.lukeewin.top
import os
import subprocess
import threading
import uuid
from datetime import timedelta, datetime
from queue import Queue
from urllib.parse import urlparse
import requests
import torch
import uvicorn
from funasr import AutoModel
from fastapi import FastAPI, UploadFile, File, Form
import logging
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv
from top.lukeewin.asr.db import SQLHelper

load_dotenv()

db_manager = SQLHelper()

def setup_logging():
    # 创建日志目录
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 创建日志器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 清除已有的处理器
    if logger.handlers:
        logger.handlers.clear()

    # 设置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 创建按时间滚动的文件处理器 - 每天午夜滚动一次，保留7天
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(log_dir, "asr_service.log"),
        when="midnight",  # 每天午夜滚动
        interval=1,  # 间隔1天
        backupCount=7,  # 保留7个备份文件
        encoding='utf-8',
        delay=False
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d.log"  # 日志文件后缀格式

    # 创建控制台处理器
    # console_handler = logging.StreamHandler()
    # console_handler.setLevel(logging.INFO)
    # console_handler.setFormatter(formatter)

    # 添加处理器到日志器
    logger.addHandler(file_handler)
    # logger.addHandler(console_handler)

    return logging.getLogger(__name__)


# 初始化日志
logger = setup_logging()

app = FastAPI()

home_directory = os.path.expanduser("~")
base_dir = os.path.join(home_directory, ".cache", "modelscope", "hub", "models")
asr_model = os.path.join(base_dir, 'FunAudioLLM', 'Fun-ASR-Nano-2512')
vad_model = os.path.join(base_dir, 'iic', 'speech_fsmn_vad_zh-cn-16k-common-pytorch')

task_queue = Queue()
result_dict = {}

_model = None

def to_date(milliseconds):
    """将时间戳转换为SRT格式的时间"""
    time_obj = timedelta(milliseconds=milliseconds)
    return f"{time_obj.seconds // 3600:02d}:{(time_obj.seconds // 60) % 60:02d}:{time_obj.seconds % 60:02d}.{time_obj.microseconds // 1000:03d}"


def response_format(code: int, status: str, message: str, data: dict = None):
    return {
        "code": code,
        "status": status,
        "message": message,
        "data": data or {}
    }

def get_model():
    global _model
    if _model is None:
        try:
            logger.info("加载模型中...")
            _model = AutoModel(
                model=asr_model,
                vad_model=vad_model,
                vad_kwargs={"max_single_segment_time": 30000},
                trust_remote_code=True,
                remote_code="./Fun-ASR/model.py",
                disable_update=True,
                disable_pbar=True,
                disable_log=True,
                ngpu=1 if torch.cuda.is_available() else 0,
                ncpu=os.cpu_count(),
            )
            logger.info("模型加载成功")
        except Exception as e:
            logger.error("模型加载失败")
            raise
    return _model


def convert_audio_to_wav(input_path, output_path):
    """
    将音频转换为16k采样率、单声道、pcm_s16le格式的wav文件
    """
    try:
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-ac', '1',
            '-ar', '16000',
            '-acodec', 'pcm_s16le',
            '-y',
            output_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            logger.error(f'{input_path} 音频转码失败')
            raise Exception(f"音频转码失败: {result.stderr}")

        logger.info(f"音频转码完成: {input_path} -> {output_path}")
        return True
    except subprocess.TimeoutExpired:
        logger.error(f'{input_path} 音频转码超时')
        raise Exception("音频转码超时")
    except Exception as e:
        logger.error(f'{input_path} 音频转码失败')
        raise Exception(f"音频转码失败: {str(e)}")


@app.post("/asr")
async def asr(file: UploadFile = File(None),
                     audio_url: str = Form(None),
                     hotwords: str = Form(None),
                     language: str = Form("中文"),
                     batch_size: int = Form(1),
                     itn: bool = Form(True)):
    task_id = str(uuid.uuid4()).replace("-", "")
    tmp_audio = None
    audio = None
    hotwords_list = []
    if hotwords:
        hotwords_list = [word.strip() for word in hotwords.split("|") if word.strip()]
    try:
        save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload")
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        if file:
            filename = file.filename
            file_extension = os.path.splitext(filename)[1].lower()
            contents = await file.read()
            tmp_audio = os.path.join(save_path, task_id + file_extension)
            with open(tmp_audio, "wb") as f:
                f.write(contents)
                f.flush()
            audio = os.path.join(save_path, task_id + "_converted.wav")
            convert_audio_to_wav(input_path=tmp_audio, output_path=audio)
            if os.path.exists(audio) and os.path.isfile(audio):
                model = get_model()
                res = model.generate(
                    input=[audio],
                    cache={},
                    batch_size=batch_size,
                    hotwords=hotwords_list if hotwords_list else [],
                    language=language,
                    itn=itn,
                )
                text = res[0]["text"]
                return response_format(code=200, status='success', message='请求成功', data=text)
        elif audio_url:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(audio_url, headers=headers, stream=True, timeout=30)
            if response.status_code == 200:
                url_path = urlparse(audio_url).path
                filename = os.path.basename(url_path)
                file_extension = os.path.splitext(filename)[1].lower()
                tmp_audio = os.path.join(save_path, task_id + file_extension)
                with open(tmp_audio, 'wb') as f:
                    f.write(response.content)
                    f.flush()
                if os.path.isfile(tmp_audio):
                    audio = os.path.join(save_path, task_id + "_converted.wav")
                    convert_audio_to_wav(input_path=tmp_audio, output_path=audio)
                    model = get_model()
                    res = model.generate(
                        input=[audio],
                        cache={},
                        batch_size=batch_size,
                        hotwords=hotwords_list if hotwords_list else [],
                        language=language,
                        itn=itn,
                    )
                    text = res[0]["text"]
                    return response_format(code=200, status='success', message='请求成功', data=text)
            else:
                logger.error(f'{task_id} 音频下载失败')
        else:
            logger.error(f'{task_id} 传入参数不正确')
    except Exception as e:
        logger.error(f'{task_id} 转写异常')
    finally:
        if os.path.exists(tmp_audio):
            os.unlink(tmp_audio)
        if os.path.exists(audio):
            os.unlink(audio)


@app.post("/asr/async")
async def asr_async(file: UploadFile = File(None),
                     audio_url: str = Form(None),
                     hotwords: str = Form(None),
                     language: str = Form("中文"),
                     batch_size: int = Form(1),
                     itn: bool = Form(True)):
    task_id = str(uuid.uuid4()).replace("-", "")
    hotwords_list = []
    if hotwords:
        hotwords_list = [word.strip() for word in hotwords.split("|") if word.strip()]
    task_type = None
    audio_content = None
    filename = None
    file_extension = None
    if file and audio_url:
        return response_format(code=300, status='success', message='不能同时传入file和audio_url', data={'task_id': task_id})
    elif file:
        filename = file.filename
        file_extension = os.path.splitext(filename)[1].lower()
        audio_content = await file.read()
        task_type = 'audio_file'
    elif audio_url:
        audio_content = audio_url
        task_type = 'audio_url'
    else:
        logger.error(f'{task_id} 传入的参数有问题')
        return response_format(code=300, status='success', message='请求参数错误', data={'task_id': task_id})
    task_queue.put({'task_id': task_id, 'task_type': task_type, 'audio_content': audio_content, 'hotwords_list': hotwords_list, 'language': language, 'batch_size': batch_size, 'itn': itn, 'filename': filename, 'file_extension': file_extension})
    return response_format(code=200, status='success', message='请求成功', data={'task_id': task_id})


def task_worker():
    model = get_model()
    sql = 'insert into asr_text (id, task_id, createtime) values (%s, %s, %s)'
    while True:
        task = task_queue.get()
        task_id = task['task_id']
        task_type = task['task_type']
        audio_content = task['audio_content']
        hotwords_list = task['hotwords_list']
        language = task['language']
        batch_size = task['batch_size']
        itn = task['itn']
        save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload")
        result_dict[task_id] = {}
        createtime = datetime.now()
        db_manager.create(sql, (task_id, task_id, createtime))
        tmp_audio = None
        audio = None
        try:
            if task_type is not None and task_type == 'audio_file':
                file_extension = task['file_extension']
                tmp_audio = os.path.join(save_path, task_id + file_extension)
                with open(tmp_audio, "wb") as f:
                    f.write(audio_content)
                    f.flush()
                audio = os.path.join(save_path, task_id + "_converted.wav")
                convert_audio_to_wav(input_path=tmp_audio, output_path=audio)
                if os.path.exists(audio) and os.path.isfile(audio):
                    model = get_model()
                    res = model.generate(
                        input=[audio],
                        cache={},
                        batch_size=batch_size,
                        hotwords=hotwords_list if hotwords_list else [],
                        language=language,
                        itn=itn,
                    )
                    text = res[0]["text"]
                    result_dict[task_id] = {'text': text}
                    updatetime = datetime.now()
                    sql1 = 'update asr_text set text = %s, updatetime = %s where task_id = %s'
                    db_manager.modify(sql1, (text, updatetime, task_id))
            elif task_type is not None and task_type == 'audio_url':
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                audio_url = audio_content
                response = requests.get(audio_url, headers=headers, stream=True, timeout=30)
                if response.status_code == 200:
                    url_path = urlparse(audio_url).path
                    filename = os.path.basename(url_path)
                    file_extension = os.path.splitext(filename)[1].lower()
                    tmp_audio = os.path.join(save_path, task_id + file_extension)
                    with open(tmp_audio, 'wb') as f:
                        f.write(response.content)
                        f.flush()
                    if os.path.isfile(tmp_audio):
                        audio = os.path.join(save_path, task_id + "_converted.wav")
                        convert_audio_to_wav(input_path=tmp_audio, output_path=audio)
                        model = get_model()
                        res = model.generate(
                            input=[audio],
                            cache={},
                            batch_size=batch_size,
                            hotwords=hotwords_list if hotwords_list else [],
                            language=language,
                            itn=itn,
                        )
                        text = res[0]["text"]
                        result_dict[task_id] = {'text': text}
                else:
                    logger.error(f'{task_id} 音频下载失败')
            else:
                logger.error(f'{task_id} 传参错误')
        except Exception as e:
            logger.error(f'{task_id} 转写异常 {e}')
        finally:
            if tmp_audio is not None and os.path.exists(tmp_audio):
                os.unlink(tmp_audio)
            if audio is not None and os.path.exists(audio):
                os.unlink(audio)


@app.get("/asr/result/{task_id}")
async def result(task_id: str):
    sql = 'select task_id, text from asr_text where task_id = %s'
    sql1 = 'delete from asr_text where task_id = %s'
    if task_id in result_dict:  # 在缓存中，直接从缓存中获取结果
        result_ = result_dict.get(task_id, None)
        if result_:
            del result_dict[task_id]  # 从缓存中删除结果
            db_manager.modify(sql1, (task_id,))  # 从数据库中删除结果
            text = result_['text']
            logger.info(f'{task_id} 命中缓存，获取结果成功')
            return response_format(code=200, status='success', message='请求成功', data={'text': text})
        else:
            logger.info(f'{task_id} 正在转写中')
            return response_format(code=201, status='success', message='正在转写中', data={'task_id': task_id})
    else:  # 不在缓存中，那么从数据库中查找
        sql_result = db_manager.get_one(sql, (task_id,))
        if sql_result is not None:
            text = sql_result['text']  # 如果 text == '' 说明存在转写任务，正在转写中
            if text is None:
                return response_format(code=201, status='success', message='正在转写中', data={'task_id': task_id})
            db_manager.modify(sql1, (task_id,))  # 获取结果之后，删除数据库中的记录
            logger.info(f'{task_id} 命中数据库，获取结果成功')
            return response_format(code=200, status='success', message='请求成功', data={'text': text})
        else:
            logger.warning(f'{task_id} 转写任务不存在')
            return response_format(code=300, status='success', message='转写任务不存在', data={'task_id': task_id})


@app.on_event("startup")
async def startup_event():
    """应用启动时预加载模型"""
    get_model()
    save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload")
    if not os.path.exists(save_path):
        os.makedirs(save_path)
    t = threading.Thread(target=task_worker, daemon=True)
    t.start()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9090)
