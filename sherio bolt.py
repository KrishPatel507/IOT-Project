import asyncio
from sphero_bolt_plus import SpheroScanner, SpheroBot

async def main():
    print("Scanning for robots...")

    scanner = SpheroScanner()
    devices = await scanner.scan_for_robots()  # ← correct method

    if not devices:
        print("No robots found. Make sure BOLT is on and not connected to another app.")
        return

    device = devices[0]  # pick the first robot found

    async with SpheroBot(device) as bolt:
        print("Connected!")

        await bolt.set_main_led(0, 255, 0)  # Green
        await bolt.roll(0, 100)
        await asyncio.sleep(2)
        await bolt.stop()
        print("Done!")

asyncio.run(main())