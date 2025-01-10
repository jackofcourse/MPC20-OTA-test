#!/usr/bin/env python3
import requests
import os
import time
import subprocess
import can
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='can_update.log'
)

# Configuration
GITHUB_RAW_URL = "https://raw.githubusercontent.com/jackofcourse/MPC20-OTA-test/main/configurationFull.gciBin"
LOCAL_DOWNLOAD_PATH = "/tmp/configurationFull.gciBin"
CAN_UPDATE_BUILD_DIR = "/Desktop/can-update-project-2/build/"
DOWNLOAD_CHECK_INTERVAL = 60  # seconds

def setup_can_interface():
    """Configure the CAN interface with required settings."""
    try:
        # Bring down the interface
        subprocess.run(["sudo", "ip", "link", "set", "down", "can0"], check=True)
        # Set the bitrate
        subprocess.run(["sudo", "ip", "link", "set", "can0", "type", "can", "bitrate", "250000"], check=True)
        # Bring up the interface
        subprocess.run(["sudo", "ip", "link", "set", "up", "can0"], check=True)
        logging.info("CAN interface configured successfully")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to configure CAN interface: {e}")
        return False

def check_and_download_file():
    """Check if a new file is available and download it."""
    try:
        # Get the file's last modified time from GitHub
        response = requests.head(GITHUB_RAW_URL)
        remote_modified = response.headers.get('last-modified')
        
        # Check if we need to download
        if not os.path.exists(LOCAL_DOWNLOAD_PATH) or should_download(remote_modified):
            response = requests.get(GITHUB_RAW_URL)
            response.raise_for_status()
            
            with open(LOCAL_DOWNLOAD_PATH, 'wb') as f:
                f.write(response.content)
            logging.info("New configuration file downloaded")
            return True
        return False
    except requests.RequestException as e:
        logging.error(f"Failed to check/download file: {e}")
        return False

def should_download(remote_modified):
    """Compare local and remote file timestamps."""
    if not os.path.exists(LOCAL_DOWNLOAD_PATH):
        return True
    
    local_modified = datetime.fromtimestamp(os.path.getmtime(LOCAL_DOWNLOAD_PATH))
    remote_modified = datetime.strptime(remote_modified, '%a, %d %b %Y %H:%M:%S GMT')
    return remote_modified > local_modified

def send_can_message():
    """Send the specified CAN message."""
    try:
        bus = can.interface.Bus(channel='can0', bustype='socketcan')
        
        # Create 29-bit message with ID 18FF14FA and data[0] = 1
        msg = can.Message(
            arbitration_id=0x18FF14FA,
            is_extended_id=True,
            data=[1, 0, 0, 0, 0, 0, 0, 0]
        )
        
        bus.send(msg)
        logging.info("CAN message sent successfully")
        return True
    except Exception as e:
        logging.error(f"Failed to send CAN message: {e}")
        return False

def wait_for_response():
    """Wait for a response on PGN 65301."""
    try:
        bus = can.interface.Bus(channel='can0', bustype='socketcan')
        timeout = 10  # seconds to wait for response
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            msg = bus.recv(timeout=1)
            if msg is None:
                continue
                
            # Check if message is PGN 65301 (0x18FF14FB)
            # Mask out the source address (last byte)
            if (msg.arbitration_id & 0x1FFFF00) == 0x18FF14FB00:
                if msg.data[0] == 1:
                    logging.info("Valid response received")
                    return True
        
        logging.warning("No valid response received within timeout")
        return False
    except Exception as e:
        logging.error(f"Error while waiting for response: {e}")
        return False

def send_update_command():
    """Send the update command with the new configuration file."""
    try:
        os.chdir(CAN_UPDATE_BUILD_DIR)
        time.sleep(1)  # Wait 1 second as requested
        
        cmd = f"qemu-aarch64-static ./can-update {LOCAL_DOWNLOAD_PATH}"
        subprocess.run(cmd, shell=True, check=True)
        logging.info("Update command executed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to execute update command: {e}")
        return False

def main():
    while True:
        try:
            if check_and_download_file():
                logging.info("New file detected, starting update process")
                
                if not setup_can_interface():
                    logging.error("Failed to setup CAN interface")
                    continue
                
                if not send_can_message():
                    logging.error("Failed to send CAN message")
                    continue
                
                if not wait_for_response():
                    logging.error("Did not receive valid response")
                    continue
                
                if not send_update_command():
                    logging.error("Failed to send update command")
                    continue
                
                logging.info("Update process completed successfully")
            
            time.sleep(DOWNLOAD_CHECK_INTERVAL)
            
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            time.sleep(DOWNLOAD_CHECK_INTERVAL)

if __name__ == "__main__":
    main()
