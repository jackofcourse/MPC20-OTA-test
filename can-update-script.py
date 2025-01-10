#!/usr/bin/env python3
import requests
import os
import time
import subprocess
import can
from datetime import datetime
import logging

# Configure logging to both file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('can_update.log'),
        logging.StreamHandler()
    ]
)

# Configuration
GITHUB_RAW_URL = "https://raw.githubusercontent.com/jackofcourse/MPC20-OTA-test/main/configurationFull.gciBin"
LOCAL_DOWNLOAD_PATH = "/tmp/configurationFull.gciBin"
CAN_UPDATE_BUILD_DIR = "/home/jackson/Desktop/can-update-project-2/build"
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
        # Get the file with headers that prevent caching
        headers = {
            'If-Modified-Since': '0',
            'Cache-Control': 'no-cache,must-revalidate,max-age=0'
        }
        
        # First make a HEAD request to get the last modified time
        head_response = requests.head(GITHUB_RAW_URL, headers=headers)
        remote_modified = head_response.headers.get('last-modified')
        
        if not remote_modified:
            logging.info("No last-modified header found, downloading file anyway")
            needs_download = True
        else:
            local_modified = None
            if os.path.exists(LOCAL_DOWNLOAD_PATH):
                local_modified = datetime.utcfromtimestamp(os.path.getmtime(LOCAL_DOWNLOAD_PATH))
                remote_modified_dt = datetime.strptime(remote_modified, '%a, %d %b %Y %H:%M:%S GMT')
                
                logging.info(f"Local file modified: {local_modified} UTC")
                logging.info(f"Remote file modified: {remote_modified_dt} UTC")
                
                needs_download = remote_modified_dt > local_modified
            else:
                needs_download = True
        
        if needs_download:
            logging.info("Downloading new version of file")
            response = requests.get(GITHUB_RAW_URL, headers=headers)
            response.raise_for_status()
            
            with open(LOCAL_DOWNLOAD_PATH, 'wb') as f:
                f.write(response.content)
            
            # Update the local file's modification time to match the remote
            if remote_modified:
                remote_modified_dt = datetime.strptime(remote_modified, '%a, %d %b %Y %H:%M:%S GMT')
                os.utime(LOCAL_DOWNLOAD_PATH, (remote_modified_dt.timestamp(), remote_modified_dt.timestamp()))
            
            logging.info("New configuration file downloaded successfully")
            return True
        else:
            logging.info("Local file is up to date")
            return False
            
    except requests.RequestException as e:
        logging.error(f"Failed to check/download file: {e}")
        return False

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
        timeout = 120  # seconds to wait for response
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            msg = bus.recv(timeout=1)
            if msg is None:
                continue
                
            # Check if message is PGN 65301 (0x18FF14FB)
            if msg is not None:
                # Check for any message from SA 3 with data[0] = 1
                source_addr = msg.arbitration_id & 0xFF
                if source_addr == 3 and msg.data[0] == 1:
                    logging.info(f"Valid response received from SA: {source_addr}")
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
    logging.info("Starting CAN update script")
    while True:
        try:
            logging.info("Checking for new file...")
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
            
        except KeyboardInterrupt:
            logging.info("Script stopped by user")
            break
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            time.sleep(DOWNLOAD_CHECK_INTERVAL)

if __name__ == "__main__":
    print("Script starting...")
    main()
