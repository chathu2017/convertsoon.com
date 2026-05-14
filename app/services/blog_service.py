import os
import frontmatter
import markdown
from datetime import datetime
from typing import List, Optional, Dict

BLOG_DIR = "articles"

class BlogService:
    def __init__(self):
        self.posts_cache: Dict[str, dict] = {}
        self.load_posts()

    def load_posts(self):
        """ෆයිල් ඔක්කොම කියවලා මෙමරි එකට (Cache) ගන්නවා"""
        temp_posts = {}
        
        if not os.path.exists(BLOG_DIR):
            print(f"Warning: '{BLOG_DIR}' folder not found.")
            return

        for filename in os.listdir(BLOG_DIR):
            if filename.endswith(".md"):
                filepath = os.path.join(BLOG_DIR, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        post = frontmatter.load(f) 
                        slug = filename.replace(".md", "")
                        html_content = markdown.markdown(
                            post.content, 
                            extensions=['fenced_code', 'tables', 'toc']
                        )
                        
                        temp_posts[slug] = {
                            "slug": slug,
                            "title": post.get("title", "No Title"),
                            "description": post.get("description", ""),
                            "date": post.get("date", datetime.now()), 
                            "author": post.get("author", "ConvertSoon Team"),
                            "image": post.get("image", "/static/images/default-blog.jpg"), # Default Image
                            "content": html_content,
                            "tags": post.get("tags", [])
                        }
                except Exception as e:
                    print(f"Error loading post {filename}: {e}")

        self.posts_cache = dict(sorted(temp_posts.items(), key=lambda x: x[1]['date'], reverse=True))
        print(f"✅ Blog Engine Loaded: {len(self.posts_cache)} articles found.")

    def get_all_posts(self) -> List[dict]:
        return list(self.posts_cache.values())

    def get_post(self, slug: str) -> Optional[dict]:
        return self.posts_cache.get(slug)

    def refresh(self):
        self.load_posts()

blog_service = BlogService()
