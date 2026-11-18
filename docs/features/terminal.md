# Terminal

Connect to devices in a range that you are authorized to access.
Wait until the range is ready before opening a connection.
Available protocols depend on the scenario, image, and backend.

## SSH access

The browser terminal opens an SSH session for the selected device.
The platform checks access on connection and while the session is active.

### Connect via SSH

1. Open **Terminal**.
2. Select a device tab.
3. Wait for the connection status and prompt.
4. Run only commands authorized for that guest.

If the session closes, read the displayed reason before selecting **Reconnect**.
A permission failure needs current authorization; refreshing cannot grant it.

### Layout options

Select **Tabs** for one visible terminal or **Split** for two panes.
Choose each pane's device separately.
Changing a device closes that pane's old connection and opens another.
Keep long-running work in a guest session that can survive reconnection.

## RDP access

RDP uses a server-brokered Guacamole session in another browser tab.
An RDP button does not prove that the guest has a working desktop service.

### Connect via RDP

1. Select the device in **Terminal**.
2. Select **RDP**.
3. Permit the portal's new tab if your browser blocks it.
4. Wait for the queued session or read the reported error.

### RDP availability

Check the scenario's access contract and the operator's image qualification.
Do not infer RDP support from an OS name alone.
The first-range Linux smoke exercise declares SSH access to both devices.

## File transfers

File transfer requires a Guacamole connection with SFTP support and an approved transfer root.
It is not available through every SSH or RDP connection.

### Upload files

1. Open a connection that supports file transfer.
2. Press **Ctrl+Shift+Alt** to open the Guacamole menu.
3. Open **Devices**.
4. Use the file browser to upload an approved file.

### Download files

1. Open **Devices** in the Guacamole menu.
2. Select the authorized file to download.
3. Store it in the approved local destination.

### File locations

The image's recorded upload root determines the transfer location.
Built-in defaults are `/home/kali`, `/home/ubuntu`, and `C:\Users\Administrator\Downloads` for their corresponding images.
A custom image can use another root.
Ask the operator if the connection does not expose a file browser.

## Instance types

The installed scenario defines its device names, roles, images, and protocols.
NGFW management uses its [separate access flow](ngfw.md#accessing-ngfw-management).

## Tips

Keep downloaded credentials and exercise files private.
Use [terminal troubleshooting](../how-to/troubleshooting.md#terminal-issues) when a connection fails.
