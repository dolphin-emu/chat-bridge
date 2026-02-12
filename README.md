# Dolphin Chat Bridge

Chat Bridge bridges Dolphin development channels on IRC and Discord.

This is not meant as a general purpose application. It is custom made for Dolphin's needs and likely not directly usable for other projects.

## Setup

```bash
$ nix run
```

## Development

```bash
$ nix develop
$ poetry install
$ poetry run black --check .
$ poetry run pytest
$ poetry run chat-bridge --config config.yml
```
