"""Arranca la app local: http://127.0.0.1:8765  (usa --host 0.0.0.0 para verla desde otra máquina)."""

import argparse
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Motion Studio: motion graphics para vídeos faceless")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="abre el navegador al arrancar")
    args = parser.parse_args()
    if args.open:
        webbrowser.open(f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}")
    uvicorn.run("studio.server:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
