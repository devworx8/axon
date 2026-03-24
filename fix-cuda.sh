#!/bin/bash
# Fix Ollama CUDA symlinks for GPU inference on GTX 1060 6GB
# Run this with: sudo bash ~/.devbrain/fix-cuda.sh
#
# Problem: Ollama 0.18.2 ships broken symlinks in /usr/local/lib/ollama/cuda_v12/
# pointing at CUDA 12.8.x libs that don't exist (system has CUDA 12.4.x).
# This makes Ollama fall back to CPU (gpu_count=0, total_vram=0 B).

set -e

CUDA_DIR="/usr/local/lib/ollama/cuda_v12"

echo "=== Ollama GPU Fix Script ==="
echo ""

# Verify GPU is present
if ! command -v nvidia-smi &>/dev/null; then
    echo "ERROR: nvidia-smi not found. No NVIDIA GPU detected."
    exit 1
fi
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
echo "Driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader)"

# Check system CUDA libs
echo ""
echo "System CUDA libraries:"
ls -la /usr/lib/x86_64-linux-gnu/libcudart.so.12* 2>/dev/null || echo "  WARNING: libcudart.so.12 not found"
ls -la /usr/lib/x86_64-linux-gnu/libcublas.so.12* 2>/dev/null || echo "  WARNING: libcublas.so.12 not found"

echo ""
echo "Ollama CUDA dir ($CUDA_DIR):"
ls -la "$CUDA_DIR/" 2>/dev/null || echo "  Directory empty or can't list"

# Fix permissions on cuda_v12 dir
chmod 755 "$CUDA_DIR"

# Fix libcudart
if [ -L "$CUDA_DIR/libcudart.so.12" ] || [ -f "$CUDA_DIR/libcudart.so.12" ]; then
    rm -f "$CUDA_DIR/libcudart.so.12"
fi
ln -sf /usr/lib/x86_64-linux-gnu/libcudart.so.12 "$CUDA_DIR/libcudart.so.12"
echo "✓ Fixed libcudart.so.12"

# Fix libcublas
if [ -L "$CUDA_DIR/libcublas.so.12" ] || [ -f "$CUDA_DIR/libcublas.so.12" ]; then
    rm -f "$CUDA_DIR/libcublas.so.12"
fi
ln -sf /usr/lib/x86_64-linux-gnu/libcublas.so.12 "$CUDA_DIR/libcublas.so.12"
echo "✓ Fixed libcublas.so.12"

# Also fix libcublasLt if it exists broken
if [ -L "$CUDA_DIR/libcublasLt.so.12" ]; then
    rm -f "$CUDA_DIR/libcublasLt.so.12"
    ln -sf /usr/lib/x86_64-linux-gnu/libcublasLt.so.12 "$CUDA_DIR/libcublasLt.so.12"
    echo "✓ Fixed libcublasLt.so.12"
fi

echo ""
echo "New state:"
ls -la "$CUDA_DIR/"

echo ""
echo "=== Restarting Ollama ==="
pkill -f "ollama serve" 2>/dev/null || true
sleep 2

# Start ollama and check GPU detection
echo "Starting Ollama..."
ollama serve > /tmp/ollama-gpu-test.log 2>&1 &
sleep 3

# Check GPU detection
echo ""
echo "GPU detection check:"
grep -E "inference compute|gpu_count|vram|CUDA" /tmp/ollama-gpu-test.log 2>/dev/null | head -5
echo ""

VRAM=$(grep "total_vram" /tmp/ollama-gpu-test.log 2>/dev/null | head -1)
if echo "$VRAM" | grep -q '"0 B"'; then
    echo "❌ GPU still not detected. VRAM = 0 B"
    echo "Try: curl -fsSL https://ollama.com/install.sh | sh"
else
    echo "✅ GPU detected! $VRAM"
    echo ""
    echo "Now switch to 7b model for better quality:"
    echo "  python3 -c \"import sqlite3; db=sqlite3.connect('/home/edp/.devbrain/devbrain.db'); db.execute(\\\"INSERT OR REPLACE INTO settings (key, value) VALUES ('ollama_model', 'qwen2.5-coder:7b')\\\")\"; db.commit()\""
fi
