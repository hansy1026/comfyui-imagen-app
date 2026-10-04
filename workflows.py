"""Local ComfyUI workflows, expressed as API prompts and editable fields."""

import math
import secrets
import sys
from pathlib import Path


def field(key, label, group, kind, default, hint, choices=(), minimum=None, maximum=None):
    return dict(key=key, label=label, group=group, kind=kind, default=default,
                hint=hint, choices=choices, minimum=minimum, maximum=maximum)


RATIOS = {
    "1:1 (Square)": (1, 1), "2:3 (Portrait Photo)": (2, 3),
    "3:2 (Photo)": (3, 2), "3:4 (Portrait Standard)": (3, 4),
    "4:3 (Standard)": (4, 3), "9:16 (Portrait Widescreen)": (9, 16),
    "16:9 (Widescreen)": (16, 9), "21:9 (Ultrawide)": (21, 9),
}

SAMPLERS = ("euler", "euler_ancestral", "heun", "dpmpp_2m", "dpmpp_sde", "uni_pc")
SCHEDULERS = ("simple", "normal", "karras", "exponential", "sgm_uniform", "ddim_uniform")

QWEN_FIELDS = [
    field("prompt", "正面提示词", "创作内容", "text", "", "描述希望生成的主体、场景、风格和光线。"),
    field("negative_prompt", "负面提示词", "创作内容", "text", "", "描述不希望出现的内容；CFG 为 1 时通常不起作用。"),
    field("aspect_ratio", "画面比例", "画面尺寸", "choice", "1:1 (Square)", "决定横图、竖图或方图。", tuple(RATIOS)),
    field("megapixels", "目标百万像素", "画面尺寸", "float", 1.0, "控制总像素量；数值越大越清晰，也越占显存、越慢。", minimum=0.1, maximum=16),
    field("multiple", "尺寸对齐倍数", "画面尺寸", "int", 8, "宽高会取最接近该倍数的整数；通常保持 8。", minimum=8, maximum=128),
    field("manual_size", "手动指定宽高", "画面尺寸", "bool", False, "开启后改用下面的宽高，画面比例与百万像素不再决定尺寸。"),
    field("width", "手动宽度", "画面尺寸", "int", 1024, "手动模式下的输出宽度；越大越占显存。", minimum=16, maximum=16384),
    field("height", "手动高度", "画面尺寸", "int", 1024, "手动模式下的输出高度；越大越占显存。", minimum=16, maximum=16384),
    field("batch_size", "每次生成张数", "画面尺寸", "int", 1, "同一次任务输出多少张图；增加会显著占用显存。", minimum=1, maximum=64),
    field("seed", "随机种子", "采样控制", "int", 593103825222985, "相同参数和种子通常能复现相近结果。", minimum=0, maximum=18446744073709551615),
    field("random_seed", "每次随机种子", "采样控制", "bool", False, "每次提交前生成新种子；关闭后使用上面的固定种子。"),
    field("steps", "采样步数", "采样控制", "int", 25, "增加步数通常更慢；效果不保证持续提升。", minimum=1, maximum=10000),
    field("cfg", "提示词引导强度 CFG", "采样控制", "float", 1.0, "原工作流为 1；提高后负面提示词才可能产生作用，也可能改变画面稳定性。", minimum=0, maximum=100),
    field("sampler_name", "采样器", "采样控制", "choice", "euler", "改变每一步的采样算法；换用其他算法可能改变画风和速度。", SAMPLERS),
    field("scheduler", "噪声调度", "采样控制", "choice", "simple", "控制采样步数在噪声区间的分配；不同选择会改变细节。", SCHEDULERS),
    field("denoise", "去噪强度", "采样控制", "float", 1.0, "原工作流为 1；降低会改变采样过程，纯文生图通常保持 1。", minimum=0, maximum=1),
    field("unet_name", "生成模型", "模型与编码", "choice", "qwen_image_2.1_int8_convrot.safetensors", "主要决定画面能力与风格；所选文件必须已安装。"),
    field("weight_dtype", "模型权重精度", "模型与编码", "choice", "default", "影响模型加载精度和显存占用；不确定时保持 default。", ("default", "fp8_e4m3fn", "fp8_e5m2")),
    field("clip_name", "文字编码模型", "模型与编码", "choice", "qwen3vl_8b_w4a8.safetensors", "负责理解提示词；必须与生成模型兼容。"),
    field("clip_type", "文字编码类型", "模型与编码", "choice", "qwen_image", "原工作流使用 qwen_image；改错可能导致加载失败。", ("qwen_image",)),
    field("clip_device", "文字编码设备", "模型与编码", "choice", "default", "决定编码模型放置位置；默认由 ComfyUI 自动选择。", ("default", "cpu")),
    field("vae_name", "图像解码模型 VAE", "模型与编码", "choice", "qwen_image_2.1_vae_bf16.safetensors", "把潜空间结果还原成图像；应与生成模型匹配。"),
    field("text_resolution", "参考图编码分辨率", "模型与编码", "int", 1024, "仅在接入参考图时影响参考图缩放；当前纯文生图不会受它影响。", minimum=0, maximum=4096),
    field("filename_prefix", "文件名前缀", "输出文件", "str", "Qwen_image_2.1", "保存在 ComfyUI 输出目录时使用的文件名前缀。"),
    field("format", "输出格式", "输出文件", "choice", "png", "PNG 保留透明度；EXR 适合高动态范围；AVIF 会去掉透明通道以兼容编码器。", ("png", "exr", "avif")),
    field("bit_depth", "颜色位深", "输出文件", "choice", "8-bit", "PNG 可选 8/16 位；EXR 固定 32 位浮点；AVIF 依格式设置。"),
    field("input_color_space", "输入色彩空间", "输出文件", "choice", "sRGB", "决定保存时如何解释颜色；普通图像保持 sRGB。"),
    field("crf", "AVIF 压缩质量 CRF", "输出文件", "int", 18, "仅 AVIF 生效；数值越低质量越高、文件越大。", minimum=1, maximum=63),
    field("save_mode", "AVIF 保存方式", "输出文件", "choice", "still images", "仅 AVIF 生效；可分别保存静态图或合成动画。", ("still images", "animated")),
    field("fps", "AVIF 动画帧率", "输出文件", "float", 6.0, "仅 AVIF 动画生效；数值越高播放越快。", minimum=0.01, maximum=1000),
    field("loop_count", "AVIF 动画循环次数", "输出文件", "int", 0, "仅 AVIF 动画生效；0 表示无限循环。", minimum=0, maximum=1000),
]

KREA_FIELDS = [
    field("prompt", "正面提示词", "创作内容", "text", "", "描述希望生成的主体、场景、风格和光线。"),
    field("negative_prompt", "负面提示词", "创作内容", "text", "", "原工作流在此节点之后清零负面条件，因此调整它目前不会改变生成结果。"),
    field("width", "图像宽度", "画面尺寸", "int", 1024, "输出宽度；6 GB 显存建议先用 1024 或更低。", minimum=16, maximum=16384),
    field("height", "图像高度", "画面尺寸", "int", 1024, "输出高度；增大尺寸会显著增加显存与耗时。", minimum=16, maximum=16384),
    field("batch_size", "每次生成张数", "画面尺寸", "int", 1, "同一次任务输出多少张图；增加会显著占用显存。", minimum=1, maximum=64),
    field("seed", "随机种子", "采样控制", "int", 42, "相同参数和种子通常能复现相近结果。", minimum=0, maximum=18446744073709551615),
    field("random_seed", "每次随机种子", "采样控制", "bool", False, "每次提交前生成新种子；关闭后使用上面的固定种子。"),
    field("steps", "采样步数", "采样控制", "int", 8, "原工作流为 8；增加通常会变慢，效果未必更好。", minimum=1, maximum=10000),
    field("cfg", "提示词引导强度 CFG", "采样控制", "float", 1.0, "原工作流为 1；提高可能改变提示词服从程度，但负面条件仍被清零。", minimum=0, maximum=100),
    field("sampler_name", "采样器", "采样控制", "choice", "euler", "改变采样算法；不同选择可能改变画风和速度。", SAMPLERS),
    field("scheduler", "噪声调度", "采样控制", "choice", "simple", "控制各步噪声分配；不同选择会改变细节。", SCHEDULERS),
    field("denoise", "去噪强度", "采样控制", "float", 1.0, "原工作流为 1；纯文生图通常保持 1。", minimum=0, maximum=1),
    field("unet_name", "GGUF 生成模型", "模型与编码", "choice", "Krea-2-Turbo-Q3_K_M-3.91bpw.gguf", "决定模型量化版本与显存需求；所选文件必须已安装。"),
    field("clip_name", "文字编码模型", "模型与编码", "choice", "qwen3vl_4b_fp8_scaled.safetensors", "负责理解提示词；必须与 Krea2 模型兼容。"),
    field("clip_type", "文字编码类型", "模型与编码", "choice", "krea2", "原工作流使用 krea2；改错可能导致加载失败。", ("krea2",)),
    field("clip_device", "文字编码设备", "模型与编码", "choice", "default", "决定编码模型放置位置；默认由 ComfyUI 自动选择。", ("default", "cpu")),
    field("vae_name", "图像解码模型 VAE", "模型与编码", "choice", "qwen_image_vae.safetensors", "把潜空间结果还原成图像；应与模型匹配。"),
    field("filename_prefix", "文件名前缀", "输出文件", "str", "Krea2_turbo_gguf", "原工作流使用 SaveImage，输出为 PNG。"),
]

def picked(fields, *keys):
    return [dict(next(item for item in fields if item["key"] == key)) for key in keys]


QWEN_EDIT_FIELDS = picked(QWEN_FIELDS, "prompt", "negative_prompt") + [
    field("reference_count", "参考图张数", "参考图片", "int", 1, "选择 1–6 张；图 1 是主图，后续图片按顺序参与融合。", minimum=1, maximum=6),
] + [field(f"image_{i}", f"参考图 {i}" + ("（主图，必选）" if i == 1 else "（按张数启用）"),
           "参考图片", "file", "", f"上传图片；提示词中用 <image{i}> 指代。") for i in range(1, 7)] + picked(
    QWEN_FIELDS, "text_resolution", "manual_size", "width", "height", "seed", "random_seed", "steps", "cfg",
    "sampler_name", "scheduler", "denoise", "unet_name", "weight_dtype", "clip_name", "clip_type", "clip_device",
    "vae_name", "filename_prefix", "format", "bit_depth", "input_color_space", "crf", "save_mode", "fps", "loop_count") + [
    field("cache_device", "参考图缓存位置", "模型与编码", "choice", "auto", "自动分配；显存紧张可试 cpu。", ("auto", "gpu", "cpu", "off")),
    field("cache_dtype", "参考图缓存精度", "模型与编码", "choice", "default", "int8/int4 降低缓存占用，也可能影响细节。", ("default", "int8", "int4")),
]
next(x for x in QWEN_EDIT_FIELDS if x["key"] == "prompt")["default"] = "Keep the subject in <image1> recognizable. Preserve identity, shape, colors and important details while creating a clean commercial image."
next(x for x in QWEN_EDIT_FIELDS if x["key"] == "text_resolution")["default"] = 0
next(x for x in QWEN_EDIT_FIELDS if x["key"] == "text_resolution")["hint"] = "0 使用原图尺寸；大图可能超出 6 GB 显存，可改为 768 或更低。"
next(x for x in QWEN_EDIT_FIELDS if x["key"] == "manual_size")["default"] = False
next(x for x in QWEN_EDIT_FIELDS if x["key"] == "manual_size")["hint"] = "默认关闭，输出跟随参考图 1；开启后使用下方宽高。"
next(x for x in QWEN_EDIT_FIELDS if x["key"] == "width")["default"] = 768
next(x for x in QWEN_EDIT_FIELDS if x["key"] == "height")["default"] = 1152
next(x for x in QWEN_EDIT_FIELDS if x["key"] == "filename_prefix")["default"] = "Qwen_2.1_多参考图编辑"

QWEN_ALPHA_FIELDS = picked(QWEN_FIELDS, "prompt", "negative_prompt") + [
    field("cutout_mode", "上传原图抠出主体", "参考图片", "bool", False, "开启后上传原图，输出尺寸跟随原图；关闭时从文字生成。"),
    field("source_image", "人物 / 产品原图", "参考图片", "file", "", "仅抠图模式使用；保留主体并移除背景。"),
] + picked(QWEN_FIELDS, "aspect_ratio", "megapixels", "multiple", "manual_size", "width", "height", "text_resolution",
           "seed", "random_seed", "steps", "cfg", "sampler_name", "scheduler", "denoise", "unet_name", "weight_dtype",
           "clip_name", "clip_type", "clip_device", "vae_name", "filename_prefix", "bit_depth")
next(x for x in QWEN_ALPHA_FIELDS if x["key"] == "prompt")["default"] = "This is an RGBA image with transparency. A single red ceramic coffee mug, centered, clean product asset, crisp edges, no floor and no cast shadow. The image has alpha channel and the background is transparent."
next(x for x in QWEN_ALPHA_FIELDS if x["key"] == "steps")["default"] = 40
next(x for x in QWEN_ALPHA_FIELDS if x["key"] == "filename_prefix")["default"] = "Qwen_2.1_透明背景"
next(x for x in QWEN_ALPHA_FIELDS if x["key"] == "bit_depth")["choices"] = ("8-bit", "16-bit")
next(x for x in QWEN_ALPHA_FIELDS if x["key"] == "text_resolution")["hint"] = "仅抠图模式下决定原图编码尺寸。"

KREA_STYLE_FIELDS = picked(KREA_FIELDS, "prompt") + [
    field("reference_image", "风格参考图", "参考图片", "file", "", "上传一张风格图；画面主体仍由提示词决定。"),
] + picked(KREA_FIELDS, "width", "height", "seed", "random_seed", "steps", "cfg", "sampler_name", "scheduler",
           "denoise", "unet_name", "clip_name", "clip_type", "clip_device", "vae_name") + [
    field("lora_strength", "参考风格强度", "模型与编码", "float", 1.0, "降低会减弱参考图风格。", minimum=0, maximum=4),
    field("max_shift", "采样最大偏移", "采样控制", "float", 1.15, "官方参考模板值为 1.15；通常保持不变。", minimum=0, maximum=100),
    field("base_shift", "采样基础偏移", "采样控制", "float", 0.5, "官方参考模板值为 0.5；通常保持不变。", minimum=0, maximum=100),
] + picked(KREA_FIELDS, "filename_prefix")
next(x for x in KREA_STYLE_FIELDS if x["key"] == "prompt")["default"] = "A cinematic portrait of a traveler on a quiet coastal road at dusk. Use the colors, lighting, texture and artistic style of Picture 1 while keeping the traveler and scene described here as the main content."
for key, value in (("width", 1024), ("height", 1024), ("filename_prefix", "Krea2_参考图风格迁移")):
    next(x for x in KREA_STYLE_FIELDS if x["key"] == key)["default"] = value

KREA_CINEMA_FIELDS = [dict(x) for x in KREA_FIELDS] + [
    field("lora_strength", "电影感 LoRA 强度", "模型与编码", "float", 1.0, "降低可减弱柔和运动模糊。", minimum=0, maximum=4),
]
for key, value in (("prompt", "A lone traveler in a dark coat on a windswept seaside road at sunset, a vintage car passing in the distance, cinematic wide shot, restrained color palette, warm backlight and deep shadows, subtle 35mm film grain, realistic textures, ethereal motion blur style"),
                   ("width", 1344), ("height", 768), ("filename_prefix", "Krea2_sunsetblur_电影感")):
    next(x for x in KREA_CINEMA_FIELDS if x["key"] == key)["default"] = value

WORKFLOWS = {
    "qwen": {"name": "Qwen-image-2.1 无限制生图", "family": "qwen", "fields": QWEN_FIELDS},
    "krea": {"name": "Krea2 生图", "family": "krea", "fields": KREA_FIELDS},
    "qwen_edit": {"name": "Qwen Image 2.1 多参考图编辑（1–6 张）", "family": "qwen", "fields": QWEN_EDIT_FIELDS},
    "qwen_alpha": {"name": "Qwen Image 2.1 透明背景 / 抠图", "family": "qwen", "fields": QWEN_ALPHA_FIELDS},
    "krea_style": {"name": "Krea2 参考图风格迁移", "family": "krea", "fields": KREA_STYLE_FIELDS},
    "krea_cinema": {"name": "Krea2 高级电影感生图", "family": "krea", "fields": KREA_CINEMA_FIELDS},
}


def defaults(flow):
    return {item["key"]: item["default"] for item in WORKFLOWS[flow]["fields"]}


def image_fields(flow, params):
    if flow == "qwen_edit":
        return [f"image_{i}" for i in range(1, params["reference_count"] + 1)]
    if flow == "qwen_alpha" and params["cutout_mode"]:
        return ["source_image"]
    if flow == "krea_style":
        return ["reference_image"]
    return []


def coerce(flow, raw):
    result = {}
    for item in WORKFLOWS[flow]["fields"]:
        key, kind = item["key"], item["kind"]
        value = raw[key]
        try:
            if kind == "bool":
                value = bool(value)
            elif kind == "int":
                value = int(str(value).strip())
            elif kind == "float":
                value = float(str(value).strip())
                if not math.isfinite(value):
                    raise ValueError("数值必须有限")
            else:
                value = str(value).strip()
                if kind == "choice" and key in {"aspect_ratio", "format", "save_mode"} and value not in item["choices"]:
                    raise ValueError("不在可选范围内")
                if kind == "choice" and not value:
                    raise ValueError("不能为空")
            if item["minimum"] is not None and value < item["minimum"]:
                raise ValueError(f"不能小于 {item['minimum']}")
            if item["maximum"] is not None and value > item["maximum"]:
                raise ValueError(f"不能大于 {item['maximum']}")
            result[key] = value
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{item['label']}：{exc}") from exc
    prefix = result["filename_prefix"].replace("\\", "/")
    if not prefix or prefix.startswith("/") or ":" in prefix or ".." in prefix.split("/"):
        raise ValueError("文件名前缀必须是普通名称或相对目录，不能包含盘符或上级目录")
    if not result["prompt"]:
        raise ValueError("请填写正面提示词")
    for key in image_fields(flow, result):
        if not result[key] or not Path(result[key]).is_file():
            raise ValueError(f"请为“{next(x['label'] for x in WORKFLOWS[flow]['fields'] if x['key'] == key)}”选择已有图片")
    if result["random_seed"]:
        result["seed"] = secrets.randbelow(2**63)
    if flow in {"qwen", "qwen_edit"}:
        allowed = {
            "png": (("8-bit", "16-bit"), ("sRGB",)),
            "exr": (("32-bit float",), ("sRGB", "HDR", "linear")),
            "avif": (("auto", "8-bit YUV420", "10-bit YUV420"), ("sRGB", "HDR", "HDR PQ")),
        }
        depths, colors = allowed[result["format"]]
        if result["bit_depth"] not in depths or result["input_color_space"] not in colors:
            raise ValueError("输出位深或色彩空间与所选格式不匹配")
    if flow == "qwen_alpha" and result["bit_depth"] not in {"8-bit", "16-bit"}:
        raise ValueError("透明背景工作流须保存为 PNG 8/16 位")
    return result


def qwen_size(p):
    if p["manual_size"]:
        return p["width"], p["height"]
    wr, hr = RATIOS[p["aspect_ratio"]]
    scale = math.sqrt(p["megapixels"] * 1024 * 1024 / (wr * hr))
    multiple = p["multiple"]
    return round(wr * scale / multiple) * multiple, round(hr * scale / multiple) * multiple


def build_prompt(flow, p):
    if flow == "qwen":
        width, height = qwen_size(p)
        fmt = {"format": p["format"], "format.bit_depth": p["bit_depth"],
               "format.input_color_space": p["input_color_space"]}
        if p["format"] == "avif":
            fmt["format.crf"] = p["crf"]
            fmt["format.save_mode"] = p["save_mode"]
            if p["save_mode"] == "animated":
                fmt["format.save_mode.fps"] = p["fps"]
                fmt["format.save_mode.loop_count"] = p["loop_count"]
        graph = {
            "451": {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet_name"], "weight_dtype": p["weight_dtype"]}},
            "453": {"class_type": "CLIPLoader", "inputs": {"clip_name": p["clip_name"], "type": p["clip_type"], "device": p["clip_device"]}},
            "454": {"class_type": "VAELoader", "inputs": {"vae_name": p["vae_name"]}},
            "452": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["453", 0], "prompt": p["prompt"], "negative_prompt": p["negative_prompt"], "resolution": p["text_resolution"], "images": {}}},
            "456": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": p["batch_size"]}},
            "458": {"class_type": "KSampler", "inputs": {"model": ["451", 0], "positive": ["452", 0], "negative": ["452", 1], "latent_image": ["456", 0], "seed": p["seed"], "steps": p["steps"], "cfg": p["cfg"], "sampler_name": p["sampler_name"], "scheduler": p["scheduler"], "denoise": p["denoise"]}},
            "457": {"class_type": "VAEDecode", "inputs": {"samples": ["458", 0], "vae": ["454", 0]}},
            "461": {"class_type": "SaveImageAdvanced", "inputs": {"images": ["457", 0], "filename_prefix": p["filename_prefix"], **fmt}},
        }
        if p["format"] == "avif":
            graph["460"] = {"class_type": "SplitImageWithAlpha", "inputs": {"image": ["457", 0]}}
            graph["461"]["inputs"]["images"] = ["460", 0]
        return graph
    if flow in {"qwen_edit", "qwen_alpha"}:
        editing = flow == "qwen_edit"
        encoder = "474" if editing else "452"
        graph = {
            "451": {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet_name"], "weight_dtype": p["weight_dtype"]}},
            "453": {"class_type": "CLIPLoader", "inputs": {"clip_name": p["clip_name"], "type": p["clip_type"], "device": p["clip_device"]}},
            "454": {"class_type": "VAELoader", "inputs": {"vae_name": p["vae_name"]}},
            encoder: {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["453", 0], "vae": ["454", 0],
                "prompt": p["prompt"], "negative_prompt": p["negative_prompt"], "resolution": p["text_resolution"]}},
            "458": {"class_type": "KSampler", "inputs": {"model": ["451", 0], "positive": [encoder, 0],
                "negative": [encoder, 1], "latent_image": [encoder, 2], "seed": p["seed"], "steps": p["steps"],
                "cfg": p["cfg"], "sampler_name": p["sampler_name"], "scheduler": p["scheduler"], "denoise": p["denoise"]}},
            "457": {"class_type": "VAEDecode", "inputs": {"samples": ["458", 0], "vae": ["454", 0]}},
        }
        if editing:
            for i in range(1, p["reference_count"] + 1):
                image_id = str(480 + i)
                graph[image_id] = {"class_type": "LoadImage", "inputs": {"image": p[f"image_{i}"]}}
                graph[encoder]["inputs"][f"images.image_{i}"] = [image_id, 0]
            graph["469"] = {"class_type": "QwenImage21Cache", "inputs": {"model": ["451", 0],
                "device": p["cache_device"], "dtype": p["cache_dtype"]}}
            graph["458"]["inputs"]["model"] = ["469", 0]
            if p["manual_size"]:
                graph["456"] = {"class_type": "EmptyLatentImage", "inputs": {"width": p["width"], "height": p["height"], "batch_size": 1}}
                graph["458"]["inputs"]["latent_image"] = ["456", 0]
            fmt = {"format": p["format"], "format.bit_depth": p["bit_depth"], "format.input_color_space": p["input_color_space"]}
            if p["format"] == "avif":
                fmt.update({"format.crf": p["crf"], "format.save_mode": p["save_mode"]})
                if p["save_mode"] == "animated":
                    fmt.update({"format.save_mode.fps": p["fps"], "format.save_mode.loop_count": p["loop_count"]})
            graph["461"] = {"class_type": "SaveImageAdvanced", "inputs": {"images": ["457", 0], "filename_prefix": p["filename_prefix"], **fmt}}
            if p["format"] == "avif":
                graph["460"] = {"class_type": "SplitImageWithAlpha", "inputs": {"image": ["457", 0]}}
                graph["461"]["inputs"]["images"] = ["460", 0]
        else:
            if p["cutout_mode"]:
                graph["470"] = {"class_type": "LoadImage", "inputs": {"image": p["source_image"]}}
                graph[encoder]["inputs"]["images.image_1"] = ["470", 0]
            else:
                graph[encoder]["inputs"]["images"] = {}
                width, height = qwen_size(p)
                graph["456"] = {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
                graph["458"]["inputs"]["latent_image"] = ["456", 0]
            graph["461"] = {"class_type": "SaveImageAdvanced", "inputs": {"images": ["457", 0],
                "filename_prefix": p["filename_prefix"], "format": "png", "format.bit_depth": p["bit_depth"],
                "format.input_color_space": "sRGB"}}
        return graph
    if flow == "krea_style":
        return {
            "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": p["unet_name"]}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": p["clip_name"], "type": p["clip_type"], "device": p["clip_device"]}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": p["vae_name"]}},
            "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "krea2_style_reference.safetensors", "strength_model": p["lora_strength"]}},
            "5": {"class_type": "LoadImage", "inputs": {"image": p["reference_image"]}},
            "6": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "image1": ["5", 0], "prompt": p["prompt"]}},
            "7": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["6", 0], "reference_latents_method": "index_timestep_zero"}},
            "8": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},
            "9": {"class_type": "ModelSamplingFlux", "inputs": {"model": ["4", 0], "max_shift": p["max_shift"], "base_shift": p["base_shift"], "width": p["width"], "height": p["height"]}},
            "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": p["seed"]}},
            "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": p["sampler_name"]}},
            "12": {"class_type": "BasicScheduler", "inputs": {"model": ["9", 0], "scheduler": p["scheduler"], "steps": p["steps"], "denoise": p["denoise"]}},
            "13": {"class_type": "CFGGuider", "inputs": {"model": ["9", 0], "positive": ["7", 0], "negative": ["8", 0], "cfg": p["cfg"]}},
            "14": {"class_type": "EmptyLatentImage", "inputs": {"width": p["width"], "height": p["height"], "batch_size": 1}},
            "15": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["10", 0], "guider": ["13", 0], "sampler": ["11", 0], "sigmas": ["12", 0], "latent_image": ["14", 0]}},
            "16": {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["3", 0]}},
            "17": {"class_type": "SaveImage", "inputs": {"images": ["16", 0], "filename_prefix": p["filename_prefix"]}},
        }
    if flow == "krea_cinema":
        graph = build_prompt("krea", p)
        graph["11"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0],
            "lora_name": "krea2_sunsetblur.safetensors", "strength_model": p["lora_strength"]}}
        graph["8"]["inputs"]["model"] = ["11", 0]
        return graph
    if flow == "krea":
        return {
            "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": p["unet_name"]}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": p["clip_name"], "type": p["clip_type"], "device": p["clip_device"]}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": p["vae_name"]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": p["prompt"]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": p["negative_prompt"]}},
            "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
            "7": {"class_type": "EmptyLatentImage", "inputs": {"width": p["width"], "height": p["height"], "batch_size": p["batch_size"]}},
            "8": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["6", 0], "latent_image": ["7", 0], "seed": p["seed"], "steps": p["steps"], "cfg": p["cfg"], "sampler_name": p["sampler_name"], "scheduler": p["scheduler"], "denoise": p["denoise"]}},
            "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
            "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": p["filename_prefix"]}},
        }
    raise ValueError("未知工作流")


def self_test():
    for flow in WORKFLOWS:
        p = defaults(flow)
        p["prompt"] = "测试画面"
        for key in image_fields(flow, p):
            p[key] = sys.executable
        p = coerce(flow, p)
        for key in image_fields(flow, p):
            p[key] = "uploaded.png"
        graph = build_prompt(flow, p)
        assert all("class_type" in node and "inputs" in node for node in graph.values())
        if flow == "qwen_edit":
            assert graph["474"]["inputs"]["images.image_1"] == ["481", 0]
            assert graph["458"]["inputs"]["latent_image"] == ["474", 2]
            assert "456" not in graph and graph["474"]["inputs"]["resolution"] == 0
        if flow == "qwen_alpha":
            assert graph["461"]["inputs"]["format"] == "png"
        if flow == "krea_style":
            assert graph["6"]["inputs"]["image1"] == ["5", 0]
        if flow == "krea_cinema":
            assert graph["8"]["inputs"]["model"] == ["11", 0]
    p = defaults("qwen")
    assert qwen_size(p) == (1024, 1024)
    p["manual_size"], p["width"], p["height"] = True, 768, 1152
    assert build_prompt("qwen", p)["456"]["inputs"]["width"] == 768
    p["format"], p["bit_depth"], p["save_mode"] = "avif", "auto", "animated"
    assert build_prompt("qwen", p)["461"]["inputs"]["format.save_mode.fps"] == 6.0
    p = defaults("qwen_edit")
    p["reference_count"] = 6
    for i in range(1, 7):
        p[f"image_{i}"] = f"ref{i}.png"
    graph = build_prompt("qwen_edit", p)
    assert graph["474"]["class_type"] == "TextEncodeQwenImage21"
    assert len([key for key in graph["474"]["inputs"] if key.startswith("images.image_")]) == 6
    p["manual_size"] = True
    assert build_prompt("qwen_edit", p)["458"]["inputs"]["latent_image"] == ["456", 0]
    p = defaults("qwen_alpha")
    p["cutout_mode"], p["source_image"] = True, "source.png"
    assert build_prompt("qwen_alpha", p)["458"]["inputs"]["latent_image"] == ["452", 2]


if __name__ == "__main__":
    self_test()
    print("workflow checks passed")
