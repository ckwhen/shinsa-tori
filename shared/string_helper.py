import unicodedata

def clean_empty_and_type(input_val) -> str:
    """基礎清洗：將各種空值、NaN 轉為空字串，其餘轉為純字串並去首尾空格"""
    if input_val is None:
        return ""

    if isinstance(input_val, float) and input_val != input_val:
        return ""

    return str(input_val).strip()

def convert_full_to_half(input: str):
    return unicodedata.normalize('NFKC', input)