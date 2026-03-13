#!/usr/bin/env python3
"""
收集魅族论坛全部的帖子ID并存储到SQLite数据库
只存储 forum_id 和 post_id，可幂重复运行
"""

import sqlite3
import requests
import time
from typing import Dict, Any
import logging
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('forum_collector.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 论坛ID映射
FORUM_IDS = {
    '主理人': 213,
    '魅族手机': 149,
    'Flyme': 60,
    '魅族商城': 216,
    'FlymeAuto': 212,
    '无界智行': 221,
    '综合讨论': 22,
    'PANDAER': 205,
    '魅友家': 104,
    'StarV': 223,
    'lipro': 203,
    '魅族校园': 211,
    '摄影天地': 84,
    '魅友记': 214,
    '社区办公室': 13,
    '二手交易': 20,
    '我有一个朋友': 215
}

class ForumPostCollector:
    def __init__(self, db_path: str = "forum_posts.db"):
        self.db_path = db_path
        self.api_base = "https://myplus-api.meizu.cn/myplus-qing/ug/forum/content/list/all"
        self.session = requests.Session()

        # 配置重试策略
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.init_database()

    def init_database(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建帖子表，只存储 forum_id 和 post_id
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                forum_id INTEGER,
                post_id INTEGER,
                collect_time INTEGER,
                PRIMARY KEY (forum_id, post_id)
            )
        ''')

        conn.commit()
        conn.close()
        logger.info(f"数据库初始化完成，数据库文件: {self.db_path}")

    def fetch_posts(self, forum_id: int, page: int = 0) -> Dict[str, Any]:
        """获取论坛帖子列表"""
        params = {
            'forumId': forum_id,
            'orderBy': 2,
            'markId': '',
            'page': page
        }


        while True:
            try:
                response = self.session.get(self.api_base, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                if data.get('msg', '') == '操作太快了，请过会再试':
                    logger.warning(f"请求过快，等待10秒后重试 forumId={forum_id}, page={page}")
                    time.sleep(10)
                    continue
                return data
            except Exception as e:
                logger.error(f"请求失败 forumId={forum_id}, page={page}: {e}")
                return {}

    def collect_forum_posts(self, forum_id: int, forum_name: str) -> int:
        """收集单个论坛的所有帖子"""
        logger.info(f"开始收集论坛: {forum_name} (ID: {forum_id})")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        total_posts = 0
        page = 0
        has_more = True

        while has_more:
            time.sleep(0.5)
            data = self.fetch_posts(forum_id, page)

            if not data or 'data' not in data:
                logger.warning(f"forumId={forum_id} page={page} 返回数据为空")
                break

            posts_data = data.get('data', {})
            if not isinstance(posts_data, dict):
                logger.warning(f"forumId={forum_id} page={page} data不是字典格式")
                break

            posts = posts_data.get('blocks', [])
            has_more = posts_data.get('hasMore', False)

            if not posts:
                logger.info(f"forumId={forum_id} page={page} 没有更多帖子")
                break

            # 处理帖子数据
            for post in posts:
                # 从 detail 中获取 post_id
                if 'detail' in post:
                    detail = post['detail']
                    post_id = detail.get('id')
                    if not post_id:
                        continue

                    # 检查是否已存在
                    cursor.execute('SELECT 1 FROM posts WHERE forum_id = ? AND post_id = ?', (forum_id, post_id))
                    if cursor.fetchone():
                        continue

                    # 插入新记录
                    cursor.execute('''
                        INSERT INTO posts (forum_id, post_id, collect_time)
                        VALUES (?, ?, ?)
                    ''', (forum_id, post_id, int(time.time())))

                    total_posts += 1
                    if total_posts % 100 == 0:
                        logger.info(f"已收集 {total_posts} 个帖子...")

            conn.commit()
            page += 1
            logger.info(f"forumId={forum_id} page={page-1} 完成，收集了 {len(posts)} 个帖子，总计 {total_posts} 个")

        conn.close()
        logger.info(f"论坛 {forum_name} (ID: {forum_id}) 收集完成，共收集 {total_posts} 个新帖子")
        return total_posts

    def collect_all_posts(self):
        """收集所有论坛的帖子"""
        logger.info("开始收集所有论坛的帖子")

        total_new_posts = 0

        for forum_name, forum_id in FORUM_IDS.items():
            try:
                new_posts = self.collect_forum_posts(forum_id, forum_name)
                total_new_posts += new_posts
            except Exception as e:
                logger.error(f"收集论坛 {forum_name} (ID: {forum_id}) 时出错: {e}")
                continue

        logger.info(f"所有论坛收集完成！共收集了 {total_new_posts} 个新帖子")

        # 显示统计信息
        self.show_statistics()

    def show_statistics(self):
        """显示数据库统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 总帖子数
        cursor.execute('SELECT COUNT(*) FROM posts')
        total_posts = cursor.fetchone()[0]

        # 按论坛统计
        cursor.execute('''
            SELECT forum_id, COUNT(*) as count
            FROM posts
            GROUP BY forum_id
            ORDER BY count DESC
        ''')
        forum_stats = cursor.fetchall()

        conn.close()

        logger.info("\n=== 数据库统计信息 ===")
        logger.info(f"总帖子数: {total_posts}")
        logger.info("\n各论坛帖子数:")
        for forum_id, count in forum_stats:
            forum_name = [k for k, v in FORUM_IDS.items() if v == forum_id][0]
            logger.info(f"  {forum_name} (ID: {forum_id}): {count}")

def main():
    collector = ForumPostCollector()
    collector.collect_all_posts()

if __name__ == "__main__":
    main()