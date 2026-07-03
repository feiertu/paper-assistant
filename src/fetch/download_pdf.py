"""PDF 下载模块。

支持断点续传（HTTP Range）和内嵌重试：
- 断点续传：通过 Range 头，从已下载的字节处继续
- 内层重试：每个 chunk 写入失败时重试（最多 3 次）
- 外层重试：整体下载失败时重试（最多 3 次，指数退避）
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import requests
from requests.exceptions import RequestException

import config
from src.logging_config import get_logger

logger = get_logger(__name__)

DATA_DIR: Path = config.RAW_PDF_DIR


# ---------- 断点续传下载 ----------


def _head_content_length(url: str, timeout: int = 30) -> Optional[int]:
    """发 HEAD 请求获取 Content-Length。失败返回 None。"""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        cl = resp.headers.get("Content-Length")
        return int(cl) if cl else None
    except RequestException:
        return None


def download_with_resume(
    pdf_url: str,
    arxiv_id: str,
    dest_dir: Optional[Path] = None,
    max_retries: int = 3,
    chunk_retries: int = 3,
) -> bool:
    """断点续传 + 内嵌重试下载 PDF。

    策略：
      1. 检查本地已有文件大小 → 用 Range: bytes=X- 续传
      2. 每个 chunk 写入失败 → 重试最多 chunk_retries 次
      3. 整体失败 → 指数退避重试最多 max_retries 次

    Args:
        pdf_url: PDF 下载地址
        arxiv_id: 论文 ID，用作文件名
        dest_dir: 目标目录，默认 config.RAW_PDF_DIR
        max_retries: 外层整体重试次数
        chunk_retries: 内层每 chunk 重试次数

    Returns:
        True 下载成功，False 失败
    """
    dest = Path(dest_dir) if dest_dir else DATA_DIR
    dest.mkdir(parents=True, exist_ok=True)
    file_path = dest / f"{arxiv_id}.pdf"

    # 检查是否需要下载
    total_size = _head_content_length(pdf_url)
    if file_path.exists() and total_size is not None:
        local_size = file_path.stat().st_size
        if local_size == total_size:
            logger.info("已存在（完整）: %s", arxiv_id)
            return True
        resume_pos = local_size
        logger.info("[RESUME] %s: 已下载 %d/%d bytes，续传中…", arxiv_id, local_size, total_size)
    elif file_path.exists():
        # 无法获取 Content-Length，保守处理：删除重下
        logger.warning("无法获取文件大小，删除已有文件重新下载: %s", arxiv_id)
        file_path.unlink()
        resume_pos = 0
    else:
        resume_pos = 0

    # 外层重试
    for attempt in range(1, max_retries + 1):
        try:
            _stream_download(
                pdf_url, file_path, resume_pos, chunk_retries=chunk_retries
            )
            logger.info("下载成功: %s", arxiv_id)
            return True
        except Exception as e:
            if attempt < max_retries:
                wait = 2 ** attempt  # 指数退避: 2, 4, 8 秒
                logger.warning(
                    "[RETRY] %s: 第 %d/%d 次重试失败，%ds 后重试… (%s)",
                    arxiv_id, attempt, max_retries, wait, e,
                )
                time.sleep(wait)
                # 刷新断点位置
                if file_path.exists():
                    resume_pos = file_path.stat().st_size
                else:
                    resume_pos = 0
            else:
                logger.error("[FAIL] %s: %d 次重试均失败: %s", arxiv_id, max_retries, e)
                return False

    return False


def _stream_download(
    url: str,
    file_path: Path,
    resume_pos: int,
    chunk_retries: int = 3,
    timeout: int = 120,
    chunk_size: int = 8192,
) -> None:
    """流式下载辅助函数：支持 Range 续传 + 按 chunk 重试。

    Args:
        url: 下载 URL
        file_path: 目标文件路径
        resume_pos: 断点字节位置（0 = 全新下载）
        chunk_retries: 每个 chunk 写入失败最大重试次数
        timeout: 请求超时（秒）
        chunk_size: 每次读取的 chunk 大小
    """
    headers = {}
    mode = "ab" if resume_pos > 0 else "wb"
    if resume_pos > 0:
        headers["Range"] = f"bytes={resume_pos}-"

    response = requests.get(url, stream=True, headers=headers, timeout=timeout)
    response.raise_for_status()

    with open(file_path, mode) as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not chunk:
                continue
            # 内层 chunk 重试
            for c_attempt in range(1, chunk_retries + 1):
                try:
                    f.write(chunk)
                    break
                except OSError as e:
                    if c_attempt < chunk_retries:
                        time.sleep(0.5)
                    else:
                        raise OSError(
                            f"chunk 写入失败，已重试 {chunk_retries} 次: {e}"
                        ) from e
        f.flush()


# ---------- 简易入口（兼容旧接口） ----------


def download_pdf(pdf_url: str, arxiv_id: str, dest_dir: Optional[Path] = None) -> bool:
    """简易下载入口：内部调用 download_with_resume。

    保留此接口以兼容旧代码。
    """
    return download_with_resume(pdf_url, arxiv_id, dest_dir=dest_dir)


# ---------- 批量下载 ----------


def batch_download(
    papers: list[dict],
    delay: float = 3.0,
    dest_dir: Optional[Path] = None,
) -> dict:
    """批量下载论文。

    Args:
        papers: 论文元数据列表（来自 arxiv.fetch_arxiv_metadata）
        delay: 每篇下载间隔（秒），防限速
        dest_dir: 目标目录

    Returns:
        {"success": [...], "failed": [...]}
    """
    results = {"success": [], "failed": []}

    for i, paper in enumerate(papers):
        logger.info("[%d/%d] 下载 %s…", i + 1, len(papers), paper["id"])
        if download_with_resume(paper["pdf_url"], paper["id"], dest_dir=dest_dir):
            results["success"].append(paper["id"])
        else:
            results["failed"].append(paper["id"])

        time.sleep(delay)

    return results


if __name__ == "__main__":
    from arxiv import fetch_arxiv_metadata

    query = config.ARXIV_QUERY
    max_results = config.ARXIV_MAX_RESULTS
    logger.info("[fetch] query=%s max_results=%d", query, max_results)
    papers = fetch_arxiv_metadata(query, max_results=max_results)
    results = batch_download(papers, delay=config.PDF_DOWNLOAD_DELAY)
    logger.info("成功: %d, 失败: %d", len(results["success"]), len(results["failed"]))
