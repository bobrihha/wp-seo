"""Demo access code management system."""

import json
import os
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict


@dataclass
class DemoCode:
    """A demo access code with usage limits."""
    code: str
    articles_limit: int
    images_limit: int
    articles_used: int = 0
    images_used: int = 0
    created_at: str = ""
    last_used: str = ""
    label: str = ""
    active: bool = True
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    @property
    def articles_remaining(self) -> int:
        return max(0, self.articles_limit - self.articles_used)
    
    @property
    def images_remaining(self) -> int:
        return max(0, self.images_limit - self.images_used)
    
    @property
    def is_exhausted(self) -> bool:
        return self.articles_remaining == 0 and self.images_remaining == 0
    
    def can_use_article(self) -> bool:
        return self.active and self.articles_remaining > 0
    
    def can_use_image(self) -> bool:
        return self.active and self.images_remaining > 0
    
    def use_article(self):
        if self.can_use_article():
            self.articles_used += 1
            self.last_used = datetime.now().isoformat()
    
    def use_image(self):
        if self.can_use_image():
            self.images_used += 1
            self.last_used = datetime.now().isoformat()


class DemoCodeManager:
    """Manages demo access codes."""
    
    def __init__(self, storage_path: str = "data/demo_codes.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.codes: Dict[str, DemoCode] = {}
        self._load()
    
    def _load(self):
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text())
                for code_data in data.get("codes", []):
                    code = DemoCode(**code_data)
                    self.codes[code.code] = code
            except Exception as e:
                print(f"Error loading demo codes: {e}")
    
    def _save(self):
        data = {
            "codes": [asdict(code) for code in self.codes.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    
    def generate_code(self, articles_limit: int = 10, images_limit: int = 10, label: str = "", prefix: str = "DEMO") -> DemoCode:
        while True:
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            code_str = f"{prefix}-{suffix}"
            if code_str not in self.codes:
                break
        
        code = DemoCode(code=code_str, articles_limit=articles_limit, images_limit=images_limit, label=label)
        self.codes[code_str] = code
        self._save()
        return code
    
    def generate_batch(self, count: int = 20, articles_limit: int = 10, images_limit: int = 10, prefix: str = "DEMO") -> List[DemoCode]:
        codes = []
        for i in range(count):
            code = self.generate_code(articles_limit=articles_limit, images_limit=images_limit, label=f"Batch #{i+1}", prefix=prefix)
            codes.append(code)
        return codes
    
    def get_code(self, code_str: str) -> Optional[DemoCode]:
        return self.codes.get(code_str.upper().strip())
    
    def validate_code(self, code_str: str) -> tuple[bool, str]:
        code = self.get_code(code_str)
        if not code:
            return False, "Неверный код доступа"
        if not code.active:
            return False, "Код деактивирован"
        if code.is_exhausted:
            return False, "Лимит по коду исчерпан"
        return True, f"Осталось: {code.articles_remaining} статей, {code.images_remaining} изображений"
    
    def use_article(self, code_str: str) -> bool:
        code = self.get_code(code_str)
        if code and code.can_use_article():
            code.use_article()
            self._save()
            return True
        return False
    
    def use_image(self, code_str: str) -> bool:
        code = self.get_code(code_str)
        if code and code.can_use_image():
            code.use_image()
            self._save()
            return True
        return False
    
    def deactivate_code(self, code_str: str) -> bool:
        code = self.get_code(code_str)
        if code:
            code.active = False
            self._save()
            return True
        return False
    
    def reactivate_code(self, code_str: str) -> bool:
        code = self.get_code(code_str)
        if code:
            code.active = True
            self._save()
            return True
        return False
    
    def reset_code(self, code_str: str, articles_limit: int = 10, images_limit: int = 10) -> bool:
        code = self.get_code(code_str)
        if code:
            code.articles_used = 0
            code.images_used = 0
            code.articles_limit = articles_limit
            code.images_limit = images_limit
            code.active = True
            self._save()
            return True
        return False
    
    def delete_code(self, code_str: str) -> bool:
        code_str = code_str.upper().strip()
        if code_str in self.codes:
            del self.codes[code_str]
            self._save()
            return True
        return False
    
    def get_all_codes(self) -> List[DemoCode]:
        return list(self.codes.values())
    
    def get_stats(self) -> dict:
        total = len(self.codes)
        active = len([c for c in self.codes.values() if c.active])
        exhausted = len([c for c in self.codes.values() if c.is_exhausted])
        total_articles = sum(c.articles_used for c in self.codes.values())
        total_images = sum(c.images_used for c in self.codes.values())
        return {
            "total_codes": total,
            "active_codes": active,
            "exhausted_codes": exhausted,
            "total_articles_generated": total_articles,
            "total_images_generated": total_images,
        }
