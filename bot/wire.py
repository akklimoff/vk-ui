import json


def wire_value(value):
    # VK ждёт списки через запятую, вложенные объекты — строкой JSON, булевы — числом;
    # обёртка vk_api делает это сама, но VkApi.method отправляет значения как есть
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (list, tuple)) and all(isinstance(item, (str, int, float)) for item in value):
        return ",".join(str(item) for item in value)
    return wire_json(value)


def wire_json(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple, dict)) else value
