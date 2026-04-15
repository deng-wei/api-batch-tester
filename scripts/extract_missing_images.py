import json
import os
import base64

def main():
    jsonl_path = "/mnt/data/Project/qwen-image/批量测试/output/male/results.jsonl"
    man_dir = "/mnt/data/Project/qwen-image/批量测试/output/man"

    if not os.path.exists(jsonl_path):
        print(f"错误: 找不到文件 {jsonl_path}")
        return

    # 先建立 taskId -> base_name 的映射，用于推断未生成的图片名
    mapping = {}
    
    # 第一次遍历：采集所有的成功生成的图片名
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError: continue
            
            task_id = record.get("task_id", "")
            base_id = task_id.rsplit("_run", 1)[0] if "_run" in task_id else task_id
            
            for file_path in record.get("output_files", []):
                if file_path.endswith(".png"):
                    bn = os.path.basename(file_path)
                    img_base = bn.rsplit("_run", 1)[0] if "_run" in bn else bn.replace(".png", "")
                    mapping[base_id] = img_base

    print(f"成功映射 {len(mapping)} 个基准任务ID的图片名称。")

    missing_count = 0
    recovered_count = 0

    # 第二次遍历：找出缺失图片并恢复
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError: continue

            task_id = record.get("task_id", "")
            base_id = task_id.rsplit("_run", 1)[0] if "_run" in task_id else task_id
            run_suffix = task_id.rsplit("_run", 1)[1] if "_run" in task_id else ""
            
            out_files = record.get("output_files", [])
            has_png = any(f.endswith(".png") for f in out_files)
            
            if not has_png:
                response_json_path = os.path.join(man_dir, f"{task_id}_response.json")
                if not os.path.exists(response_json_path):
                    continue
                    
                # 检查 JSON 中是否有 b64_json 数据
                try:
                    with open(response_json_path, 'r', encoding='utf-8') as jf:
                        resp = json.load(jf)
                except json.JSONDecodeError:
                    continue
                    
                b64_data = None
                # 解析结构
                if "data" in resp and isinstance(resp["data"], list) and len(resp["data"]) > 0:
                    if "b64_json" in resp["data"][0]:
                        b64_data = resp["data"][0]["b64_json"]
                    elif "url" in resp["data"][0] and resp["data"][0]["url"].startswith("data:image"):
                        b64_data = resp["data"][0]["url"].split(",", 1)[1]
                elif "b64_json" in resp:
                    b64_data = resp["b64_json"]

                if b64_data:
                    missing_count += 1
                    # 推断目标图片名
                    img_base = mapping.get(base_id)
                    if img_base:
                        png_name = f"{img_base}_run{run_suffix}.png" if run_suffix else f"{img_base}.png"
                    else:
                        png_name = f"{task_id}.png"
                        
                    target_png_path = os.path.join(man_dir, png_name)
                    
                    if not os.path.exists(target_png_path):
                        if b64_data.startswith("data:image"):
                            b64_data = b64_data.split(",", 1)[1]
                            
                        image_bytes = base64.b64decode(b64_data)
                        with open(target_png_path, 'wb') as img_f:
                            img_f.write(image_bytes)
                        recovered_count += 1

    print("-" * 40)
    print(f"总计发现存在有效返回但缺少图片的任务 {missing_count} 个，成功补充保存 {recovered_count} 张。")

if __name__ == "__main__":
    main()
