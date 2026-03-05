import importlib
import inspect
import pkgutil
from typing import Dict, Type

import templates
from templates.base_template import BaseTemplate


class TemplateManager:
    def __init__(self):
        self._template_classes: Dict[str, Type[BaseTemplate]] = {}
        self._load_templates()

    def _load_templates(self):
        for _, module_name, _ in pkgutil.iter_modules(templates.__path__):
            if module_name in ("base_template", "pdf_template_mixin", "photo_album_template"):
                continue
            try:
                module = importlib.import_module(f"templates.{module_name}")
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BaseTemplate)
                            and obj is not BaseTemplate
                            and hasattr(obj, 'id')
                            and obj.id):
                        self._template_classes[obj.id] = obj
            except Exception as e:
                print(f"Warning: could not load {module_name}: {e}")

    def get_template_list(self):
        result = []
        for tid, cls in self._template_classes.items():
            try:
                inst = cls()
                result.append({"id": tid, "name": inst.name, "description": inst.description})
            except Exception:
                pass
        return result

    def get_template_fields(self, template_id: str) -> dict:
        cls = self._template_classes.get(template_id)
        if not cls:
            raise ValueError(f"Template not found: {template_id}")
        return cls().fields

    def get_template_instance(self, template_id: str) -> BaseTemplate:
        cls = self._template_classes.get(template_id)
        if not cls:
            raise ValueError(f"Template not found: {template_id}")
        return cls()
