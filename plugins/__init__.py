from importlib import util
import os
import glob


def load_plugins(handler):
    plugin_dir = os.path.dirname(__file__)
    loaded = []
    for path in glob.glob(os.path.join(plugin_dir, "*.py")):
        name = os.path.basename(path)
        if name.startswith("_"):
            continue
        try:
            spec = util.spec_from_file_location(name[:-3], path)
            module = util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "register"):
                module.register(handler)
                loaded.append(name[:-3])
        except Exception as e:
            print(f"[PLUGIN] Failed to load {name}: {e}")
    return loaded
