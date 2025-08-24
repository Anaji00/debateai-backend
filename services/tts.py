import torch
import onnx
import os
from TTS.vocoder.models.hifigan_generator import HifiganGenerator
from TTS.vocoder.configs.hifigan_config import HifiganConfig

# === Paths (relative to backend/) ===
VOCODER_CONFIG_PATH = "xtts_onnx/vo_config.json"
VOCODER_CHECKPOINT_PATH = "xtts_onnx/vo.pth"
VOCODER_ONNX_OUTPUT_PATH = "xtts_onnx/vocoder_model_int8.onnx"

# === Load config ===
print("📄 Loading vocoder config...")
config = HifiganConfig()
config.load_json(VOCODER_CONFIG_PATH)

# === Load model from checkpoint ===
print("📦 Loading vocoder checkpoint...")
model = HifiganGenerator(config)
checkpoint = torch.load(VOCODER_CHECKPOINT_PATH, map_location="cpu")
model.load_state_dict(checkpoint["model"])
model.eval()

# === Dummy input for ONNX export ===
print("🎛️ Preparing dummy input...")
dummy_input = torch.randn(1, config.audio.num_mels, 100)  # (B, num_mels, T)

# === Export to ONNX ===
print("🚀 Exporting HiFi-GAN to ONNX...")
torch.onnx.export(
    model,
    dummy_input,
    VOCODER_ONNX_OUTPUT_PATH,
    export_params=True,
    opset_version=11,
    do_constant_folding=True,
    input_names=["mel"],
    output_names=["audio"],
    dynamic_axes={
        "mel": {2: "time"},
        "audio": {1: "time"}
    }
)

print(f"✅ Exported vocoder ONNX model to: {VOCODER_ONNX_OUTPUT_PATH}")
