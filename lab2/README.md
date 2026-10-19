# Лабораторная работа: Docker Compose + KVM

Двухсервисное веб-приложение (nginx + Flask), которое собирается через Docker Compose и разворачивается в виртуальной машине под управлением KVM. Работа выполнена на MacBook с Apple M4 (macOS, arm64).

---

## 1. Описание приложения

| Сервис     | Образ                 | Технологии                         | Порт                                   |
|------------|-----------------------|------------------------------------|----------------------------------------|
| `frontend` | `lab-frontend:latest` | nginx:alpine, статический HTML/JS  | 80 внутри контейнера, **8080** снаружи |
| `backend`  | `lab-backend:latest`  | python:3.12-slim, Flask, gunicorn  | 5000, только во внутренней сети        |

**backend** (`backend/app.py`) — Flask-приложение, запускается через gunicorn на `0.0.0.0:5000`:

- `GET /api/info` возвращает JSON:
  - `message` — приветствие;
  - `container` — hostname контейнера (`socket.gethostname()`), то есть короткий ID контейнера;
  - `time` — текущее время в формате ISO 8601 (UTC).
- `GET /api/health` возвращает `{"status": "ok"}`.

**frontend** (`frontend/`) — nginx с собственным `nginx.conf`:

- `location /` отдаёт `index.html`;
- `location /api/` проксирует запросы на `http://backend:5000`. Имя `backend` резолвится встроенным DNS Docker во внутренней сети compose.

Страница `index.html` выполняет `fetch('/api/info')` и показывает сообщение, имя контейнера, время и исходный JSON. Если запрос не удался, на странице выводится текст ошибки (например, `HTTP 502 Bad Gateway`, когда бэкенд остановлен).

**compose.yaml**:

- у обоих сервисов заданы `build`, `image` и `restart: unless-stopped`;
- наружу публикуется **только** порт фронтенда `"8080:80"`; у бэкенда есть только `expose: 5000`;
- `frontend` зависит от `backend` через `depends_on`;
- оба сервиса подключены к внутренней сети `internal` (bridge), и бэкенд доступен фронтенду только через неё.

Образы основаны на мультиархитектурных `python:3.12-slim` и `nginx:alpine`. Платформо-зависимых бинарников нет: Flask и gunicorn написаны на чистом Python. Поэтому приложение без изменений собирается и на arm64 (Mac, app-vm), и на amd64.

Структура (вторая лабораторная лежит в подпапке `lab2/` репозитория `git-lab`):

```
git-lab/
└── lab2/
    ├── README.md
    ├── compose.yaml
    ├── backend/
    │   ├── app.py
    │   ├── requirements.txt
    │   └── Dockerfile
    ├── frontend/
    │   ├── index.html
    │   ├── nginx.conf
    │   └── Dockerfile
    └── screenshots/
```

Все команды `docker compose` и `scp` ниже выполняются **из каталога `lab2/`**.

---

## 2. Локальный запуск через Docker Compose

```bash
git clone https://github.com/egortr2020/git-lab.git
cd git-lab/lab2
docker compose up -d --build
docker compose ps
curl http://localhost:8080
curl http://localhost:8080/api/info
curl http://localhost:8080/api/health
docker compose down
```

Результат локального запуска (Docker Desktop, arm64):

```
$ docker compose ps
NAME              IMAGE                 COMMAND                  SERVICE    CREATED          STATUS          PORTS
lab2-backend-1    lab-backend:latest    "gunicorn --bind 0.0…"   backend    15 seconds ago   Up 14 seconds   5000/tcp
lab2-frontend-1   lab-frontend:latest   "/docker-entrypoint.…"   frontend   15 seconds ago   Up 14 seconds   0.0.0.0:8080->80/tcp, [::]:8080->80/tcp

$ curl localhost:8080/api/info
{"container":"3d23ab9de2b7","message":"Привет от backend-сервиса на Flask!","time":"2026-10-19T18:10:52.674981+00:00"}
```
У бэкенда в колонке `PORTS` указано только `5000/tcp`, без привязки к хосту, то есть снаружи он недоступен.

> На macOS порт 5000 занят AirPlay Receiver (`ControlCenter`). Поэтому `curl localhost:5000` на маке возвращает ответ `AirTunes`, а не Flask. Это ещё одна причина публиковать наружу только фронтенд.

---

## 3. Схема «ноутбук → VM → контейнеры»

```
┌─────────────────────────────────────────────────────────────────────────┐
│ MacBook (Apple M4, macOS, arm64)                                        │
│                                                                         │
│   Браузер ──► http://localhost:8080                                     │
│                    │                                                    │
│                    │  ssh -N -L 8080:localhost:8080 app-vm              │
│                    │  (ProxyJump lima-kvmhost)                          │
│                    ▼                                                    │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ Lima VM «kvmhost»  (Ubuntu 24.04, vmType: vz,                       │ │
│ │                     nestedVirtualization: true)  → есть /dev/kvm     │ │
│ │                                                                     │ │
│ │   libvirt / QEMU + KVM, сеть libvirt «default» (virbr0)              │ │
│ │                    │                                                │ │
│ │                    ▼  192.168.122.10                                │ │
│ │ ┌─────────────────────────────────────────────────────────────────┐ │ │
│ │ │ KVM VM «app-vm»  (Ubuntu 24.04 arm64 cloud image, cloud-init)   │ │ │
│ │ │                                                                 │ │ │
│ │ │   Docker Engine + docker compose                                │ │ │
│ │ │                                                                 │ │ │
│ │ │   :8080 ──► ┌──────────────────────┐   сеть compose            │ │ │
│ │ │             │ frontend  (nginx :80)│   «internal»              │ │ │
│ │ │             │  /      → index.html │                           │ │ │
│ │ │             │  /api/  → backend    │───────┐                   │ │ │
│ │ │             └──────────────────────┘       ▼                   │ │ │
│ │ │                              ┌───────────────────────────┐     │ │ │
│ │ │                              │ backend (Flask/gunicorn   │     │ │ │
│ │ │                              │          :5000)           │     │ │ │
│ │ │                              └───────────────────────────┘     │ │ │
│ │ └─────────────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

Кратко: **MacBook → Lima VM kvmhost → KVM VM app-vm → frontend nginx :80 (8080) → backend Flask :5000**

---

## 4. Почему KVM запускается во вложенной VM

KVM (Kernel-based Virtual Machine) — модуль ядра **Linux**. В macOS его нет: там используется собственный гипервизор Apple (Hypervisor.framework / Virtualization.framework). Поэтому запустить KVM прямо на маке нельзя.

Решение — **вложенная виртуализация**. Начиная с Apple Silicon M3 и macOS 15 Sequoia, Virtualization.framework умеет передавать гостевой Linux-VM аппаратные расширения виртуализации ARM (EL2). Внутри такой VM ядро Linux поднимает KVM, появляется `/dev/kvm`, и в ней можно запускать собственные KVM-машины. На M4 эта возможность есть.

Lima VM «kvmhost» создаётся с `vmType: vz` (Apple Virtualization.framework) и `nestedVirtualization: true`. Она служит KVM-хостом.

### 4.1. Диагностика на маке

```bash
sw_vers                  # версия macOS, нужна 15+
uname -m                 # arm64
sysctl kern.hv_support   # 1 — гипервизор поддерживается
```

Вывод:

```
$ sw_vers
<вставить вывод>

$ uname -m
<вставить вывод>

$ sysctl kern.hv_support
<вставить вывод>
```

### 4.2. Создание Lima VM «kvmhost»

Файл `kvmhost.yaml`:

```yaml
vmType: vz
nestedVirtualization: true
images:
  - location: "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img"
    arch: aarch64
cpus: 4
memory: 8GiB
disk: 40GiB
```

```bash
brew install lima
limactl start --name=kvmhost ./kvmhost.yaml
limactl list
limactl shell kvmhost
```

### 4.3. Диагностика внутри kvmhost

```bash
ls -l /dev/kvm
sudo apt-get install -y cpu-checker
kvm-ok
```

Вывод:

```
$ ls -l /dev/kvm
<вставить вывод, ожидается: crw-rw---- 1 root kvm 10, 232 ... /dev/kvm>

$ kvm-ok
<вставить вывод, ожидается: INFO: /dev/kvm exists
KVM acceleration can be used>
```

**Скриншот:** `kvm-ok` внутри kvmhost

![kvm-ok](screenshots/01-kvm-ok.png)

---

## 5. Создание VM в KVM

Все команды выполняются **внутри kvmhost** (`limactl shell kvmhost`).

### 5.1. Установка пакетов виртуализации

```bash
sudo apt-get update
sudo apt-get install -y qemu-system-arm qemu-efi-aarch64 qemu-utils \
                        libvirt-daemon-system virtinst
sudo usermod -aG libvirt,kvm "$USER"
sudo systemctl enable --now libvirtd

# сеть libvirt default (192.168.122.0/24, virbr0)
sudo virsh net-start default 2>/dev/null || true
sudo virsh net-autostart default
sudo virsh net-list --all
```

### 5.2. Скачивание cloud-образа Ubuntu 24.04 arm64

```bash
cd /var/lib/libvirt/images
sudo wget https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img
```

### 5.3. Диск VM: qcow2 с backing file на 20G

Базовый образ не изменяется. Все изменения VM пишутся в отдельный overlay-диск `app-vm.qcow2`:

```bash
sudo qemu-img create -f qcow2 \
  -F qcow2 -b /var/lib/libvirt/images/noble-server-cloudimg-arm64.img \
  /var/lib/libvirt/images/app-vm.qcow2 20G

sudo qemu-img info /var/lib/libvirt/images/app-vm.qcow2
```

### 5.4. cloud-init: user-data с SSH-ключом

На маке нужен SSH-ключ (`ssh-keygen -t ed25519`, если его ещё нет). Содержимое `~/.ssh/id_ed25519.pub` вставляется в `user-data`:

```bash
mkdir -p ~/cloud-init && cd ~/cloud-init

cat > user-data <<'EOF'
#cloud-config
hostname: app-vm
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...ВАШ_ПУБЛИЧНЫЙ_КЛЮЧ... user@macbook
ssh_pwauth: false
package_update: true
EOF

cat > meta-data <<'EOF'
instance-id: app-vm
local-hostname: app-vm
EOF
```

### 5.5. Статический IP через DHCP-резервацию в сети default

```bash
sudo virsh net-update default add ip-dhcp-host \
  "<host mac='52:54:00:aa:bb:01' name='app-vm' ip='192.168.122.10'/>" \
  --live --config

sudo virsh net-dumpxml default | grep -A1 "host mac"
```

### 5.6. Создание VM через virt-install

```bash
sudo virt-install \
  --name app-vm \
  --virt-type kvm \
  --arch aarch64 \
  --machine virt \
  --boot uefi \
  --vcpus 2 \
  --memory 2048 \
  --osinfo ubuntu24.04 \
  --disk path=/var/lib/libvirt/images/app-vm.qcow2,format=qcow2,bus=virtio \
  --network network=default,model=virtio,mac=52:54:00:aa:bb:01 \
  --cloud-init user-data="$HOME/cloud-init/user-data",meta-data="$HOME/cloud-init/meta-data" \
  --graphics none \
  --noautoconsole \
  --import
```

Проверка:

```bash
sudo virsh list --all
sudo virsh net-dhcp-leases default
ssh ubuntu@192.168.122.10      # проверка изнутри kvmhost
```

Вывод:

```
$ sudo virsh list --all
<вставить вывод, ожидается:  Id   Name     State
                             1    app-vm   running>

$ sudo virsh net-dhcp-leases default
<вставить вывод>
```

**Скриншот:** `virsh list`

![virsh list](screenshots/02-virsh-list.png)

---

## 6. Подтверждение, что VM работает именно на KVM

### 6.1. В kvmhost: тип домена libvirt

```bash
sudo virsh dumpxml app-vm | grep "domain type"
```

```
<вставить вывод, ожидается: <domain type='kvm' id='1'>>
```

`type='kvm'` означает аппаратное ускорение через `/dev/kvm`. При программной эмуляции QEMU TCG здесь было бы `type='qemu'`.

**Скриншот:** `domain type='kvm'`

![domain type kvm](screenshots/03-domain-type-kvm.png)

### 6.2. Внутри app-vm

```bash
ssh app-vm
systemd-detect-virt
```

```
<вставить вывод, ожидается: kvm>
```

**Скриншот:** `systemd-detect-virt`

![systemd-detect-virt](screenshots/04-systemd-detect-virt.png)

---

## 7. Деплой приложения в VM и проброс порта

### 7.1. SSH-доступ к app-vm с ноутбука

Lima генерирует SSH-конфиг для kvmhost (хост `lima-kvmhost`). app-vm находится в изолированной сети libvirt, поэтому подключение к ней идёт через kvmhost (`ProxyJump`).

`~/.ssh/config` на маке (строка `Include` должна стоять **в начале** файла, до любых блоков `Host`):

```
Include ~/.lima/kvmhost/ssh.config

Host app-vm
    HostName 192.168.122.10
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
    ProxyJump lima-kvmhost
```

Проверка:

```bash
ssh app-vm hostname        # → app-vm
```

### 7.2. Установка Docker в app-vm

```bash
ssh app-vm 'sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2'
ssh app-vm 'sudo docker version && sudo docker compose version'
```

### 7.3. Копирование файлов и запуск

Из каталога `lab2/` репозитория на маке (`cd git-lab/lab2`):

```bash
ssh app-vm 'mkdir -p ~/app'
scp -r compose.yaml backend frontend app-vm:~/app/
ssh app-vm 'cd ~/app && sudo docker compose up -d --build'
ssh app-vm 'cd ~/app && sudo docker compose ps'
```

Образы собираются прямо в app-vm под arm64 (aarch64).

Вывод:

```
$ ssh app-vm 'cd ~/app && sudo docker compose ps'
<вставить вывод>
```

**Скриншот:** `docker compose ps` в VM

![docker compose ps](screenshots/05-docker-compose-ps.png)

### 7.4. Проброс порта на ноутбук

```bash
ssh -N -L 8080:localhost:8080 app-vm
```

Команда держит туннель открытым, пока запущена. Порт `8080` на маке пробрасывается через kvmhost на `localhost:8080` внутри app-vm, где его слушает контейнер frontend.

> Перед запуском туннеля остановите локальный стек (`docker compose down`), иначе порт 8080 на маке будет занят.

---

## 8. Адрес приложения

**http://localhost:8080**

Открывается в браузере на маке, пока работает туннель из п. 7.4.

---

## 9. Проверка связи фронтенда с бэкендом

1. **Страница в браузере.** На http://localhost:8080 видны сообщение, имя контейнера, время и исходный JSON из `/api/info`. Статус «Бэкенд доступен, данные получены» подтверждает, что `fetch` прошёл через nginx до Flask.

2. **curl через туннель:**

   ```bash
   curl http://localhost:8080/api/info
   curl http://localhost:8080/api/health
   ```

   ```
   <вставить вывод, например:
   {"container":"3f2a9c1b7d4e","message":"Привет от backend-сервиса на Flask!","time":"..."}
   {"status":"ok"}>
   ```

3. **Поле `container` совпадает с контейнером бэкенда.** Hostname контейнера Docker равен первым 12 символам его ID:

   ```bash
   ssh app-vm 'cd ~/app && sudo docker compose ps'
   ssh app-vm 'cd ~/app && sudo docker compose ps -q backend | cut -c1-12'
   ssh app-vm 'cd ~/app && sudo docker compose exec backend hostname'
   ```

   ```
   <вставить вывод: значение совпадает с полем "container" из /api/info>
   ```

   Ответ на `/api/info` сформировал именно контейнер `backend`, а nginx лишь проксировал запрос по внутренней сети compose.

4. **Бэкенд не опубликован наружу.** В `docker compose ps` у `backend` в колонке `PORTS` указано только `5000/tcp`, без `0.0.0.0:...`. Запрос к нему возможен только из сети compose:

   ```bash
   ssh app-vm 'curl -s -m 2 http://localhost:5000/api/health || echo "недоступен с хоста VM"'
   ```

---

## 10. Скриншоты

Скриншоты лежат в каталоге `lab2/screenshots/` (ссылки ниже относительные, от `lab2/README.md`):

| № | Что показано                                     | Файл                                       |
|---|--------------------------------------------------|--------------------------------------------|
| 1 | `kvm-ok` внутри kvmhost                          | `screenshots/01-kvm-ok.png`                |
| 2 | `virsh list --all` (app-vm в состоянии running)  | `screenshots/02-virsh-list.png`            |
| 3 | `virsh dumpxml app-vm \| grep "domain type"` → `kvm` | `screenshots/03-domain-type-kvm.png`   |
| 4 | `systemd-detect-virt` внутри app-vm → `kvm`      | `screenshots/04-systemd-detect-virt.png`   |
| 5 | `sudo docker compose ps` в app-vm                | `screenshots/05-docker-compose-ps.png`     |
| 6 | Страница http://localhost:8080 в браузере на маке | `screenshots/06-browser.png`              |

![kvm-ok](screenshots/01-kvm-ok.png)

![virsh list](screenshots/02-virsh-list.png)

![domain type kvm](screenshots/03-domain-type-kvm.png)

![systemd-detect-virt](screenshots/04-systemd-detect-virt.png)

![docker compose ps в VM](screenshots/05-docker-compose-ps.png)

![страница в браузере](screenshots/06-browser.png)
