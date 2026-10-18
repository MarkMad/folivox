# Run Folivox in Docker

For a home server or NAS: the web studio runs in a container, you open it from any computer on your network, and the
finished audiobooks land in a folder you choose (for example your Audiobookshelf library). It works from Portainer and
Dockhand as a stack, or with plain `docker compose`. Nothing has to be typed in a terminal on the server.

> **Mac:** Docker on macOS cannot use the Apple GPU (no Metal in containers), so the container would run on the CPU,
> which is slow. On a Mac use the normal [installer](install.md). The same goes for a PC with a GPU you do not want to
> pass into Docker: the installer is simpler there.

> **Tested so far:** the CPU image on Linux arm64 (build, start, login, health check, file ownership, stop). The
> `cuda` and `cuda128` images, NVIDIA GPUs, Docker Desktop on Windows with WSL 2, Portainer and Dockhand stacks, and
> the amd64 build have **not been tested** yet; the instructions for them below are what should work, not what was seen
> working. Please report what you find.

## Quick start

1. Pick a password for the studio: at least 16 characters, for example the output of `openssl rand -hex 24`.
2. Create a stack from [docker-compose.yml](../docker-compose.yml) (CPU) or
   [docker-compose.nvidia.yml](../docker-compose.nvidia.yml) (NVIDIA GPU). In Portainer: *Stacks → Add stack → Web
   editor*, paste the file, and under *Environment variables* add `FOLIVOX_UI_TOKEN` (and the optional ones below).
3. Deploy. Open `http://<server>:8765/`, enter the password, and use the studio as on a desktop.

With plain Docker Compose:

```bash
export FOLIVOX_UI_TOKEN=$(openssl rand -hex 24)   # keep it: this is the password
echo "$FOLIVOX_UI_TOKEN"
docker compose up -d
```

The first render downloads the models (about 7.6 GB: the voice and the speech-recognition check) with a progress bar in
the studio. To fetch them at start instead, set `FOLIVOX_PRELOAD_MODELS=1`: the studio then starts only after the
download has finished (progress is in the container log; the container shows as *starting* meanwhile). They are
stored in the `folivox-data` volume, so updating or recreating the container does not download them again.

## Images

| Tag | For | Platforms |
|---|---|---|
| `ghcr.io/vatavale/folivox:cpu` (also `latest`) | No GPU | amd64, arm64 |
| `ghcr.io/vatavale/folivox:cuda` | NVIDIA GPU (PyTorch 2.5, CUDA 12.4) | amd64 |
| `ghcr.io/vatavale/folivox:cuda128` | NVIDIA RTX 50 series (PyTorch 2.7.1, CUDA 12.8) | amd64 |

Every image is also tagged with the version (`cpu-0.1.0.N`). The images contain the program and ffmpeg, not the models.
To build one yourself: `docker build -f docker/Dockerfile --build-arg VARIANT=cpu -t folivox:cpu .`
(`VARIANT` is `cpu`, `cuda` or `cuda128`).

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `FOLIVOX_UI_TOKEN` | required | The studio password (16+ characters). The studio refuses to start on the network without it. |
| `FOLIVOX_UI_TOKEN_FILE` | | Path of a file holding the token (Docker/Portainer secret), instead of the variable. |
| `PUID`, `PGID` | 1000 | The user and group that own the files the container writes (`id -u`, `id -g` on the host). |
| `FOLIVOX_PORT` (compose) | 8765 | Port on the host. |
| `FOLIVOX_AUDIOBOOKS` (compose) | volume `folivox-audiobooks` | Absolute host folder for finished audiobooks (for example `/srv/audiobooks`). Leave it unset to use a Docker volume. |
| `FOLIVOX_UI_ALLOWED_HOSTS` | any | Comma-separated host names the studio answers to (see Security). |
| `FOLIVOX_PRELOAD_MODELS` | 0 | `1`: download the models when the container starts. |
| `FOLIVOX_TAG` (compose) | `cpu` / `cuda` | Image tag. |
| `TZ` | UTC | Time zone of the log. |

API keys for cloud engines: the container has no OS keychain, so keys typed into the studio cannot be saved there.
Pass them as environment variables instead (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `FISH_API_KEY`, `CARTESIA_API_KEY`;
see [cloud-engines.md](cloud-engines.md)); the compose files have commented lines for them.

## Volumes

| Mount | Holds | Keep it? |
|---|---|---|
| `/data` (`folivox-data`) | Models, voices, settings (`config.toml`), studio state, uploaded books, Hugging Face cache | Yes: re-downloading is 7.6 GB |
| `/audiobooks` (`folivox-audiobooks`, or your folder) | Finished `.m4b` / `.mp3` | Yes: point it at your audiobook folder |
| `/work` (`folivox-work`) | Journals and finished takes of books still being rendered | Yes until the book is done: it is what lets a stopped render continue |

Work files live apart from `/audiobooks` on purpose, so Audiobookshelf never scans half-made books.
Uploaded books are kept in `/data`; the studio library lists them.

## Security

The studio can read and write files in its volumes and uses the API keys you give it, so it is protected like an admin
page:

* The password is required. Listening beyond `127.0.0.1` without `FOLIVOX_UI_TOKEN` is refused at start (a normal
  desktop install is unchanged: loopback only, with an automatically generated token). The token is never written to
  the log.
* You enter it once on a login page; the browser keeps a cookie (`SameSite=Strict`, HttpOnly, 30 days; `Secure` as soon as the request came over HTTPS,
  directly or through a proxy that sends `X-Forwarded-Proto: https`). Other sites cannot make
  your browser call the studio: cross-site requests are refused, and without the cookie or token every API call
  returns 401. A wrong password costs one second per try, and ten wrong ones within a minute lock password checks for five minutes
  (a browser that is already logged in is not affected).
* The connection is **plain HTTP**. Use it on your home network, **do not forward the port to the internet**. To reach
  it from outside, put a reverse proxy with HTTPS and your own login in front (Caddy, Traefik, nginx Proxy Manager,
  Cloudflare Tunnel, Tailscale) and bind the port to loopback or the proxy network (`"127.0.0.1:8765:8765"`). The
  proxy must pass the `Host` header unchanged (and `Origin` as the browser sent it). Set `FOLIVOX_UI_ALLOWED_HOSTS` to
  the proxy's name to refuse any other `Host` as a protection against DNS rebinding.
* The container runs as your `PUID`/`PGID`, never as root, so audiobooks are not owned by root. The compose files also
  drop every Linux capability except the three the start-up needs and set `no-new-privileges`.
* Anyone who has the password can make the studio read and write anywhere the container user can (the output folder is
  a setting). Mount only the folders you want it to see.

## NVIDIA GPU (untested)

Linux: install the NVIDIA driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
on the host, then use `docker-compose.nvidia.yml` (it reserves one GPU). Windows (untested): Docker Desktop with the WSL 2
backend and a current NVIDIA driver on Windows should work with the same file. Check with `docker exec folivox folivox doctor`.

Folivox probes CUDA in a child process before using it and falls back to the CPU if it does not work or the card has
too little memory (4 GB for the voice, 8 GB for the speech check as well), so a misconfigured GPU slows the render
down but does not break it. Use `cuda128` for RTX 50 cards: the older build has no kernels for them.

AMD and Intel GPUs: the optional native runtime has a Vulkan build ([native-runtime.md](native-runtime.md), experimental).
Passing `/dev/dri` into the container might make it usable; this is **untested**, treat it as a guess.

## Update

Pull the new image and recreate the container (Portainer: *Recreate → Re-pull image*; compose:
`docker compose pull && docker compose up -d`). Volumes are kept. A render that is running is cancelled by the stop
(its progress is saved in `/work`) and continues when you start it again.

## Command line in the container

```bash
docker exec -it folivox folivox doctor
# -u: your PUID, so files written are not owned by root; the book must be visible inside the container
docker exec -it -u 1000 folivox folivox render /audiobooks/some.epub
```

## Limits

* No Apple GPU in containers (see the note at the top).
* Books enter through the studio's upload; there is no watched input folder yet.
* The image does not contain the optional Fish Audio engines and native runtime; install them from the studio
  (they download into `/data`).
