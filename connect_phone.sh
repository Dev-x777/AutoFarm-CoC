#!/bin/bash
# =============================================================================
# AutoFarm CoC — Android Phone Connection Wizard
# Pairs your Android phone to your MacBook via ADB (USB or Wireless)
# =============================================================================

ADB="$(dirname "$0")/bin/platform-tools/adb"
PYTHON="$(dirname "$0")/.venv/bin/python3"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}${BOLD}  ⚔️  AutoFarm CoC — Device Connection Wizard      ${NC}"
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════${NC}"
    echo ""
}

print_step() {
    echo -e "${BOLD}${YELLOW}▶ $1${NC}"
}

print_ok() {
    echo -e "  ${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "  ${RED}✗ $1${NC}"
}

check_adb() {
    if [ ! -f "$ADB" ]; then
        print_error "ADB not found at $ADB. Run start.sh first to auto-download it."
        exit 1
    fi
    print_ok "ADB binary found: $ADB"
}

wait_for_usb_device() {
    echo ""
    print_step "Step 1 — Enable Developer Options on your Android phone:"
    echo "   1. Open Settings → About Phone (or About Device)"
    echo "   2. Tap 'Build Number' 7 times until you see 'You are now a developer'"
    echo "   3. Go back to Settings → Developer Options (or Additional/System Settings → Developer Options)"
    echo "   4. Enable 'USB Debugging'"
    echo ""
    print_step "Step 2 — Connect your phone via USB cable to this MacBook"
    echo "   • On your phone, tap 'Allow' when it asks 'Allow USB Debugging?'"
    echo "   • Check 'Always allow from this computer' and tap OK"
    echo ""
    echo -ne "  Waiting for device..."
    
    "$ADB" start-server > /dev/null 2>&1

    for i in $(seq 1 60); do
        UNAUTH=$("$ADB" devices | grep -v "List of devices" | grep "unauthorized" | awk '{print $1}')
        if [ -n "$UNAUTH" ]; then
            echo ""
            echo -e "  ${YELLOW}⚠️  Phone detected (${UNAUTH}) but waiting for authorization!${NC}"
            echo -e "  ${BOLD}👉 Unlock your phone screen and tap 'Allow USB Debugging' -> 'Always allow'${NC}"
            sleep 2
            continue
        fi

        DEVICE=$("$ADB" devices | grep -v "List of devices" | grep "device$" | awk '{print $1}')
        if [ -n "$DEVICE" ]; then
            echo ""
            print_ok "Phone connected via USB! Serial: $DEVICE"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo ""
    print_error "Timed out waiting for device. Check USB cable and USB Debugging."
    return 1
}

enable_wireless_adb() {
    echo ""
    print_step "Step 3 — Enabling wireless ADB on your phone..."
    
    DEVICE=$("$ADB" devices | grep -v "List of devices" | grep "device$" | awk '{print $1}')
    if [ -z "$DEVICE" ]; then
        print_error "No USB device found. Please connect via USB first."
        return 1
    fi

    # Enable TCP/IP mode on port 5555
    "$ADB" -s "$DEVICE" tcpip 5555 > /dev/null 2>&1
    sleep 1

    # Get phone's IP address (tries wlan0, then other interfaces)
    PHONE_IP=$("$ADB" -s "$DEVICE" shell ip addr show wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
    
    if [ -z "$PHONE_IP" ]; then
        # Try alternative interface names
        PHONE_IP=$("$ADB" -s "$DEVICE" shell ip route get 8.8.8.8 2>/dev/null | awk '/src/{print $7}')
    fi

    if [ -n "$PHONE_IP" ]; then
        print_ok "Phone IP address: ${PHONE_IP}"
        echo ""
        print_step "Step 4 — Connecting wirelessly to ${PHONE_IP}:5555..."
        sleep 1
        CONNECT_RESULT=$("$ADB" connect "${PHONE_IP}:5555" 2>&1)
        echo "  $CONNECT_RESULT"

        if echo "$CONNECT_RESULT" | grep -q "connected"; then
            print_ok "Wireless ADB connection established!"
            echo ""
            echo -e "  ${BOLD}You can now unplug the USB cable.${NC}"
            echo -e "  AutoFarm will connect to: ${CYAN}${PHONE_IP}:5555${NC}"
            echo ""

            # Save wireless address to config
            SERIAL="${PHONE_IP}:5555"
            sed -i '' "s/^  serial: .*/  serial: \"${SERIAL}\"/" "$(dirname "$0")/config/config.yaml"
            sed -i '' "s/^  mode: .*/  mode: \"adb\"/" "$(dirname "$0")/config/config.yaml"
            print_ok "Saved serial '${SERIAL}' to config/config.yaml"
            return 0
        else
            print_error "Wireless connection failed: $CONNECT_RESULT"
            print_step "Using USB connection instead (serial: $DEVICE)"
            sed -i '' "s/^  serial: .*/  serial: \"${DEVICE}\"/" "$(dirname "$0")/config/config.yaml"
            sed -i '' "s/^  mode: .*/  mode: \"adb\"/" "$(dirname "$0")/config/config.yaml"
            print_ok "Saved USB serial '${DEVICE}' to config/config.yaml"
            return 0
        fi
    else
        print_error "Could not determine phone's Wi-Fi IP. Make sure phone is connected to Wi-Fi."
        print_step "Using USB connection (serial: $DEVICE)"
        sed -i '' "s/^  serial: .*/  serial: \"${DEVICE}\"/" "$(dirname "$0")/config/config.yaml"
        sed -i '' "s/^  mode: .*/  mode: \"adb\"/" "$(dirname "$0")/config/config.yaml"
        print_ok "Saved USB serial '$DEVICE' to config/config.yaml"
        return 0
    fi
}

verify_game_running() {
    echo ""
    print_step "Step 5 — Checking Clash of Clans status on your phone..."
    
    # 1. Check if process is running (pidof)
    PID=$("$ADB" shell pidof com.supercell.clashofclans 2>/dev/null | tr -d '\r\n ')
    
    # 2. Check if Clash of Clans is in the foreground (supports Android 10-16)
    FOREGROUND=$("$ADB" shell "dumpsys window | grep -iE '(mCurrentFocus|mFocusedApp)'" 2>/dev/null | grep -i "supercell" | head -1)
    if [ -z "$FOREGROUND" ]; then
        FOREGROUND=$("$ADB" shell dumpsys activity activities 2>/dev/null | grep -iE "(mResumedActivity|topResumedActivity|mFocusedApp)" | grep -i "supercell" | head -1)
    fi
    
    if [ -n "$FOREGROUND" ]; then
        print_ok "Clash of Clans is in the foreground — Village detected!"
    elif [ -n "$PID" ]; then
        print_ok "Clash of Clans is running (PID: $PID) in background. Bringing to foreground..."
        "$ADB" shell monkey -p com.supercell.clashofclans -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1
        sleep 2
        print_ok "Clash of Clans brought to front!"
    else
        echo "  Clash of Clans is not currently in the foreground."
        # Check if installed
        INSTALLED=$("$ADB" shell pm list packages | grep -i "com.supercell.clashofclans")
        if [ -n "$INSTALLED" ]; then
            echo -e "  Launching Clash of Clans automatically on your phone..."
            "$ADB" shell monkey -p com.supercell.clashofclans -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1
            sleep 4
            print_ok "Clash of Clans launched! Waiting for village screen to load..."
        else
            echo "  Please:"
            echo "  • Open Clash of Clans on your phone"
            echo "  • Navigate to your village Home Screen"
            echo "  • Keep the screen ON and unlocked"
        fi
    fi

    # Keep screen awake while plugged in so phone doesn't sleep during farming
    "$ADB" shell svc power stayon usb > /dev/null 2>&1 || true
}

get_screen_info() {
    echo ""
    print_step "Detecting phone screen resolution..."
    RESOLUTION=$("$ADB" shell wm size 2>/dev/null | tail -1)
    DENSITY=$("$ADB" shell wm density 2>/dev/null | tail -1)
    MODEL=$("$ADB" shell getprop ro.product.model 2>/dev/null | tr -d '\r')
    ANDROID=$("$ADB" shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
    
    print_ok "Device: $MODEL (Android $ANDROID)"
    print_ok "Screen: $RESOLUTION | $DENSITY"
    echo ""
}

launch_bot() {
    echo ""
    echo -e "${GREEN}${BOLD}══════════════════════════════════${NC}"
    echo -e "${GREEN}${BOLD}  ✅ Phone connected & verified!   ${NC}"
    echo -e "${GREEN}${BOLD}══════════════════════════════════${NC}"
    echo ""
    echo "To start AutoFarm now, run:"
    echo -e "  ${CYAN}${BOLD}./start.sh${NC}"
    echo ""
    echo "Or start in the background:"
    echo -e "  ${CYAN}${BOLD}./start.sh --no-browser &${NC}"
    echo ""
}

# === Main Flow ===
print_header
check_adb

# Check if already wirelessly connected
EXISTING=$("$ADB" devices | grep -v "List of devices" | grep "device$" | awk '{print $1}')
if [ -n "$EXISTING" ]; then
    echo -e "  ${GREEN}✓ Device already connected: ${EXISTING}${NC}"
    get_screen_info
    verify_game_running
    launch_bot
    exit 0
fi

# Fresh connection flow
wait_for_usb_device && enable_wireless_adb && get_screen_info && verify_game_running && launch_bot
