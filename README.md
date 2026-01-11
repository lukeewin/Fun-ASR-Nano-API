<h1 align="center">Fun-ASR-Nano-API使用说明</h1>

# 1. API介绍

该项目使用阿里开源的`Fun-ASR-Nano-2512`模型。具体多种国内内外语言识别，更具体内容可以点击[这里](https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512)。

一共有三个接口，一个同步接口，一个异步接口，一个获取异步转写结果接口。

默认占用`9090`端口，如果该端口已经被占用，可以修改使用其它端口。

```markdown
同步接口 /asr
异步接口 /asr/async
获取结果接口 /asr/result/{task_id}
```

## 1.1 同步接口

适合对短音频转写，比如一句话识别。

发送POST请求，form-data形式。

```shell
curl -X POST -F "file=@your_audio" http://localhost:9090/asr
```

接口响应如下：

```json
{"code":200,"status":"success","message":"请求成功","data":"现在我来录制十秒钟的音频，来测试一下一句话识别，看看识别的速度怎么样。"}
```

也支持音频`URL`方式转写。

```shell
curl -X POST -F "audio_url=https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512/resolve/master/example/zh.mp3" http://localhost:9090/asr
```

## 1.2 异步接口

适合长音频转写。

发送POST请求，form-data形式。

```shell
curl -X POST -F "file=@your_audio" http://localhost:9090/asr/async
```

接口会响应如下。

```json
{
    "code": 200,
    "status": "success",
    "message": "请求成功",
    "data": {
        "task_id": "0a621df553ad421e98fca42684298630"
    }
}
```

## 1.3 获取结果接口

上面的异步接口中返回的`task_id`，这个接口中需要使用。

该接口发送GET请求，把`task_id`放到请求路径中。

```shell
http://localhost:9090/asr/result/0a621df553ad421e98fca42684298630
```

接口返回的code=201表示正在转写中，返回200表示转写完成，其它状态码均为异常。

```json
{
    "code": 201,
    "status": "success",
    "message": "正在转写中",
    "data": {
        "task_id": "21e73fe9d069493c9b5d1e398e3dc616"
    }
}
```

```json
{
    "code": 200,
    "status": "success",
    "message": "请求成功",
    "data": {
        "text": "我是第一个说话人，现在我录制一段声音来测试一下。 直接跑路了，我连传达的机会都没有。 我现在回到我车上，我想了一下，我明天 他24小时失联才能报警吗？我明天下午。 的时候我就去报警，但是我很庆幸的是我 今天30号。 来店里面了，如果我今天不来，他房租到期了之后，东西都搬空了，那个时候来也没有意义了，幸好。 这个是第二个人的一个声音，然后这段音频中包含了两个人的声音，一个是我自己的一个声音，然后另外一个是我播放啊，另外一个啊视频里面的一个声音。然后现在我们啊来试一下啊，现在有一分钟的一个音频了，我们试一下吧。"
    }
}
```

```json
{
    "code": 300,
    "status": "success",
    "message": "转写任务不存在",
    "data": {
        "task_id": "21e73fe9d069493c9b5d1e398e3dc618"
    }
}
```

# 2. 安装依赖

```shell
pip install funasr fastapi ffmpeg-python uvicorn transformers zhconv torch torchaudio
```

同时还需要确保你的服务器中安装`ffmpeg`并且配置了系统环境变量，以及还需要安装`MySQL`数据库，并且导入项目中的`sql`代码。

# 3. 其它

视频演示以及代码讲解，[点击这里跳转B站](https://www.bilibili.com/video/BV1x26UB2E6Y/)。

博客：https://blog.lukeewin.top

公众号：编程分享录

如果觉得这个项目对你有用，记得在右上角点击一下`Star`，非常感谢你。

如果不会部署，可微信添加`lukeewin01`，进行有偿部署，添加时需要备注来自哪个平台，为啥添加，否则不给通过。