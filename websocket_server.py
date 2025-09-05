import asyncio
import websockets
from websocket_service import handle_websocket
from utils import logger


async def websocket_handler(websocket, path):
    """Enhanced WebSocket handler with proper path routing"""
    logger.info(f"WebSocket connection attempt for path: {path}")

    # Extract call_id from path like /stream/call_id
    if not path.startswith('/stream/'):
        logger.error(f"Invalid WebSocket path: {path}")
        await websocket.close(code=1008, reason="Invalid path")
        return

    try:
        await handle_websocket(websocket, path)
    except Exception as e:
        logger.error(f"WebSocket handler error: {e}")
        await websocket.close(code=1011, reason="Internal server error")


async def main():
    logger.info("Starting WebSocket server on port 8080")

    # Start server with enhanced handler
    server = await websockets.serve(
        websocket_handler,
        "0.0.0.0",
        8080,
        # Add headers for better compatibility
        extra_headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

    logger.info("WebSocket server listening on ws://localhost:8080")
    logger.info("Ready to accept connections on /stream/<call_id>")

    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
