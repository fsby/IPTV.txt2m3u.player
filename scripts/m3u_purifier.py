import requests
from concurrent.futures import ThreadPoolExecutor
import os
import argparse
import tempfile
import shutil
import sys
import time

# 默认配置
TIMEOUT = 5
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
}

def check_url(url, max_retries=0):
    """检测 URL 状态，支持参数化重试"""
    for i in range(max_retries + 1):
        try:
            
            response = requests.head(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            
            # 404 或 5xx 认为是无效链接
            if response.status_code == 404 or response.status_code >= 500:
                if i < max_retries:
                    time.sleep(i + 1)
                    continue
                return False
            return True
        except (requests.exceptions.RequestException):
            if i < max_retries:
                time.sleep(i + 1)
                continue
            return False
    return False

def validate_block_indexed(indexed_block, max_retries):
    """处理区块并统计该频道下的链接情况"""
    index, block = indexed_block
    initial_url_count = len(block["urls"])
    valid_urls = []
    
    for url in block["urls"]:
        if check_url(url, max_retries):
            valid_urls.append(url)
    
    # 记录剔除的数量
    removed_in_block = initial_url_count - len(valid_urls)
    
    if valid_urls:
        block["urls"] = valid_urls
        return (index, block, removed_in_block)
    return (index, None, removed_in_block)

def safe_save_m3u(content_lines, output_path):
    """原子替换安全写入逻辑"""
    output_abs = os.path.abspath(output_path)
    output_dir = os.path.dirname(output_abs) or '.'
    fd, temp_path = tempfile.mkstemp(dir=output_dir, suffix='.m3u', prefix='.tmp_', text=True)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.writelines(content_lines)
        try:
            os.replace(temp_path, output_abs)
        except Exception:
            shutil.move(temp_path, output_abs)
        return True
    except Exception as e:
        if os.path.exists(temp_path): os.unlink(temp_path)
        return False

def process_file(input_file, output_file, threads, no_others, retries):
    if not os.path.exists(input_file):
        print(f"错误: 找不到文件 {input_file}")
        return False

    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    header = lines[0] if lines and lines[0].startswith("#EXTM3U") else "#EXTM3U\n"
    blocks = []
    current_block = None
    idx = 0

    # 解析区块
    total_urls_found = 0
    for line in lines[1:]:
        line = line.strip()
        if not line: continue
        if line.startswith("#EXTINF"):
            if current_block: blocks.append((idx, current_block)); idx += 1
            current_block = {"info": line, "urls": [], "others": []}
        elif line.startswith("http"):
            if current_block: 
                current_block["urls"].append(line)
                total_urls_found += 1
        elif line.startswith("#"):
            if current_block: current_block["others"].append(line)
    if current_block: blocks.append((idx, current_block))

    print(f"\n正在处理: {input_file}")
    print(f"原始链接总数: {total_urls_found} | 频道总数: {len(blocks)}")

    # 多线程检测
    results = []
    total_removed = 0
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(validate_block_indexed, b, retries) for b in blocks]
        for count, future in enumerate(futures, 1):
            idx, block, removed_count = future.result()
            results.append((idx, block))
            total_removed += removed_count
            print(f"检测进度: {count}/{len(blocks)}", end='\r')

    # 保持原序
    results.sort(key=lambda x: x[0])
    
    # 构造内容
    output_content = [header]
    valid_channels = 0
    for _, block in results:
        if block:
            output_content.append(block["info"] + "\n")
            if not no_others:
                for other in block["others"]: output_content.append(other + "\n")
            for url in block["urls"]: output_content.append(url + "\n")
            valid_channels += 1

    if safe_save_m3u(output_content, output_file):
        print(f"\n[处理完成]")
        print(f"--------------------------------")
        print(f"已剔除无效链接数: {total_removed}")
        print(f"剩余有效链接数: {total_urls_found - total_removed}")
        print(f"剩余有效频道数: {valid_channels}")
        print(f"结果已保存至: {output_file}")
        print(f"--------------------------------")
        return True
    return False

def main():
    parser = argparse.ArgumentParser(description="M3U文件内链接检测工具 (支持重试/原序/原子替换/统计)")
    parser.add_argument('-i', '--input', nargs='+', required=True, help='输入M3U文件')
    parser.add_argument('-o', '--output', help='输出路径')
    parser.add_argument('-mt', '--threads', type=int, default=15, help='线程数')
    parser.add_argument('-n', '--no-others', action='store_true', help='剔除配置行')
    parser.add_argument('-r', '--retries', type=int, default=0, help='重试次数')
    
    args = parser.parse_args()
    if args.output and len(args.input) > 1:
        sys.exit("错误: 多个输入文件时不能指定 -o")

    for input_f in args.input:
        output_f = args.output if args.output else input_f
        process_file(input_f, output_f, args.threads, args.no_others, args.retries)

if __name__ == "__main__":
    main()
