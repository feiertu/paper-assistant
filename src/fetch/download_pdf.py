import os
import time
import requests

DATA_DIR = "data/raw"

def download_pdf(pdf_url: str, arxiv_id: str) -> bool:
    os.makedirs(DATA_DIR, exist_ok=True)
    file_path = os.path.join(DATA_DIR, f"{arxiv_id}.pdf")
    
    # 自己加：检查文件是否已存在（防重复）
    if os.path.exists(file_path):
        print(f"✓ 已存在: {arxiv_id}")
        return True
    
    try:
        response = requests.get(pdf_url, stream=True, timeout=60)
        response.raise_for_status()  # 检查是否下载成功
        
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"✓ 下载成功: {arxiv_id}")
        return True
    except Exception as e:
        print(f"✗ 下载失败: {arxiv_id}, 错误: {e}")
        return False
    
    return False  # 失败返回 False


def batch_download(papers: list[dict], delay: float = 3.0) -> dict:
    results = {"success": [], "failed": []}
    
    for i, paper in enumerate(papers):
        print(f"[{i+1}/{len(papers)}] 下载 {paper['id']}...")
        if download_pdf(paper['pdf_url'], paper['id']):
            results["success"].append(paper['id'])
        else:
            results["failed"].append(paper['id'])
        
        time.sleep(delay)  # 防限速
    
    return results


if __name__ == "__main__":
    # 测试：先下载 3 篇
    from arxiv import fetch_arxiv_metadata
    
    papers = fetch_arxiv_metadata("cat:cs.AI", 3)
    results = batch_download(papers)
    print(f"成功: {len(results['success'])}, 失败: {len(results['failed'])}")