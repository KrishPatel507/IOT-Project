import asyncio
from sphero_bolt_plus import SpheroScanner
from sphero_bolt_plus.exceptions import RobotNotFoundError

async def main():
    scanner = SpheroScanner()
    bolt = None

    print("🔎 Scanning for BOLT for up to 60 seconds... Shake or tap it to start advertising!")

    # Scan repeatedly for 12 attempts (~5 seconds each, total 60 seconds)
    for attempt in range(12):
        try:
            devices = await scanner.scan_for_robots()
            if devices:
                bolt = devices[0]  # take the first detected BOLT
                print(f"✅ Found BOLT: {bolt}")
                break
        except RobotNotFoundError:
            print(f"⏳ Attempt {attempt+1}/12: No BOLT found, retrying...")
            await asyncio.sleep(5)  # wait 5 seconds before next scan

    if not bolt:
        print("❌ No BOLT detected. Make sure it is flashing continuously and not connected to another device.")
        return

    # Connect to the BOLT
    await bolt.connect()
    print("🔵 Connected to BOLT!")

    # Keep it awake by sending a command every 5 seconds
    try:
        while True:
            # Example: flash LEDs to keep alive
            await bolt.set_led_color(r=0, g=0, b=255)  # Blue LED
            await asyncio.sleep(5)
    except KeyboardInterrupt:
        print("\n🛑 Exiting...")
        await bolt.disconnect()
        print("Disconnected.")

# Run the script
asyncio.run(main())