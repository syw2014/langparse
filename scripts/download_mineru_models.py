import argparse
import os
import sys

# Step 1: Force use modelscope for high-speed download
try:
    from modelscope import snapshot_download
except ImportError:
    print("\n[!] Error: 'modelscope' not found in current Python path:", file=sys.stderr)
    print(f"[!] Executable: {sys.executable}", file=sys.stderr)
    print("[!] Run: pip install modelscope", file=sys.stderr)
    sys.exit(1)

def download_models(model_id: str, local_dir: str, revision: str = 'master'):
    """
    Downloads MinerU models from ModelScope.
    """
    print(f"[*] Repository: {model_id}")
    print(f"[*] Revision:   {revision}")
    print(f"[*] Local Path: {os.path.abspath(local_dir)}")

    try:
        # Note: modelscope.snapshot_download creates a directory structure: cache_dir/model_id
        # To match the expected langparse layout, we download to the specified directory.
        # Use cache_dir instead of local_dir to avoid some symlink issues on some platforms.
        path = snapshot_download(
            model_id=model_id,
            cache_dir=local_dir,
            revision=revision,
            # ModelScope by default does not use symlinks in the same way HF does
        )
        print(f"\n[+] Success! Models ready at: {path}")
        
        # Verify the download actually landed where we wanted
        if not os.path.exists(path):
            print(f"[!] Warning: Path {path} does not exist after download.", file=sys.stderr)
            
    except Exception as e:
        print(f"\n[!] Download failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ModelScope MinerU Downloader for LangParse")
    parser.add_argument(
        "--model_id", 
        default="opendatalab/MinerU2.5-2509-1.2B",
        help="ModelScope ID (default: opendatalab/MinerU2.5-2509-1.2B)"
    )
    parser.add_argument(
        "--output_dir", 
        default="./models/mineru",
        help="Local directory for models (default: ./models/mineru)"
    )
    parser.add_argument(
        "--revision", 
        default="master",
        help="Model revision (default: master)"
    )
    
    args = parser.parse_args()
    
    # Ensure the parent directory exists
    os.makedirs(args.output_dir, exist_ok=True)
    
    download_models(args.model_id, args.output_dir, args.revision)
