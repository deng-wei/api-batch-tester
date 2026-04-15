# 缺失图片补充脚本说明

分析了 `results.jsonl` 与 `output/man` 目录，并编写了缺失图片补充脚本 `scripts/extract_missing_images.py`。

## 发现
实际执行发现，当前目录的 2500 张图片与 2500 个有效任务是**一一对应**的。用户之所以在 `results.jsonl` 看到部分任务只有 JSON 没有 PNG，原因有二：
1. 断点续跑/重试机制：一些任务在早期执行时失败或被中断，这条失败日志保留在了 jsonl 文件中（未包含 PNG），但它在后续的重试中成功执行并正确保存了图像。
2. API 返回错误限制：例如出现 `InputImageSensitiveContentDetected` 违规情况，API 只会返回 Error JSON，这种也只有 JSON，且不可能包含 `b64_json` 的数据来补充。

如果有任务真的是有效的 `b64_json` 但漏存了，脚本可以完美根据其他 success 的记录反解出正确的图像文件名予以保存补偿！
