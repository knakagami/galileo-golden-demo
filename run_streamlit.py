#!/usr/bin/env python3
# unused but keep this because we might want to leverage it to run different domains
"""
Simple script to run the Streamlit app
"""
import subprocess
import sys
import os

def main():
    """Run the Streamlit app"""
    # Change to the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    print("🚀 Starting Galileo Multi-Domain Agent Demo...")
    print("=" * 50)
    
    try:
        # Run streamlit
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.port", "8501",
            "--server.address", "0.0.0.0",
            "--server.headless", "true",
        ], check=True)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running Streamlit: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
