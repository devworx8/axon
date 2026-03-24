#!/bin/bash
# Fix broken CUDA symlinks in Ollama's cuda_v12 directory
# Run with: sudo bash ~/.devbrain/fix-gpu.sh

set -e

CUDA_DIR="/usr/local/lib/ollama/cuda_v12"

echo "Fixing broken CUDA symlinks in $CUDA_DIR ..."

# Fix libcudart.so.12 (points to 12.8.90 which doesn't exist; system has 12.4.127)
if [ -L "$CUDA_DIR/libcudart.so.12" ]; then
    rm "$CUDA_DIR/libcudart.so.12"
fi
ln -s /usr/lib/x86_64-linux-gnu/libcudart.so.12 "$CUDA_DIR/libcudart.so.12"
echo "  Fixed libcudart.so.12"

# Fix libcublas.so.12 (points to 12.8.4.1 which doesn't exist; system has 12.4.5.8)
if [ -L "$CUDA_DIR/libcublas.so.12" ]; then
    rm "$CUDA_DIR/libcublas.so.12"
fi
ln -s /usr/lib/x86_64-linux-gnu/libcublas.so.12 "$CUDA_DIR/libcublas.so.12"
echo "  Fixed libcublas.so.12"

echo ""
echo "Done! Now restart Ollama:"
echo "  pkill ollama && ollama serve &"
echo ""
echo "Then verify GPU with:"
echo "  ollama run qwen2.5-coder:7b 'hi' && ollama ps"
