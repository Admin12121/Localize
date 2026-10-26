"""User-facing Localize entry: prepare once, then use the existing local authority."""

import sys

from web_bridge import cli
from web_bridge.setup.tunnel import SetupError, ensure_cloudflared


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        options = cli.parse_options(args)
        if options.about or options.local_only:
            return cli.main(args)
        if not options.tunnel:
            args.append("--tunnel")
        binary = cli.find_cloudflared() or ensure_cloudflared()
        return cli.main(args, tunnel_binary=binary)
    except (SetupError, OSError, ValueError) as error:
        print("Localize: " + str(error), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
