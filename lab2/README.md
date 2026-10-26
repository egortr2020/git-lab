# Лабораторная работа: Docker Compose + KVM

Двухсервисное веб-приложение (nginx + Flask), которое собирается через Docker Compose и разворачивается в виртуальной машине под управлением KVM. Работа выполнена на MacBook с Apple M4 (macOS 26, arm64). Уровень: **7 баллов**.

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

Образы основаны на мультиархитектурных `python:3.12-slim` и `nginx:alpine`. Платформо-зависимых бинарников нет, поэтому приложение без изменений собирается и на arm64 (Mac, app-vm), и на amd64.

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
    └── frontend/
        ├── index.html
        ├── nginx.conf
        └── Dockerfile
```

Все команды `docker compose` и `scp` ниже выполняются **из каталога `lab2/`**.

---

## 2. Локальный запуск через Docker Compose

```bash
git clone https://github.com/egortr2020/git-lab.git
cd git-lab/lab2
docker compose up -d --build
docker compose ps
curl localhost:8080/api/info
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

Решение — **вложенная виртуализация**. На Apple Silicon M3 и новее с macOS 15 и новее Virtualization.framework умеет передавать гостевой Linux-VM аппаратные расширения виртуализации ARM. Внутри такой VM ядро Linux поднимает KVM, появляется `/dev/kvm`, и в ней можно запускать собственные KVM-машины. На M4 эта возможность есть.

Lima VM «kvmhost» создаётся с `vmType: vz` (Apple Virtualization.framework) и `nestedVirtualization: true`. Она служит KVM-хостом. Сама kvmhost работает не на KVM, а на гипервизоре Apple, поэтому VM для приложения создаётся внутри неё, уже на KVM.

### 4.1. Диагностика на маке

```
$ sw_vers; uname -m; sysctl kern.hv_support
ProductName:		macOS
ProductVersion:		26.6.2
BuildVersion:		25G83
arm64
kern.hv_support: 1
```

macOS 26 (новее 15), архитектура arm64 (Apple M4), гипервизор доступен (`kern.hv_support: 1`).

### 4.2. Создание Lima VM «kvmhost»

```bash
brew install lima
limactl start --name=kvmhost --vm-type=vz \
  --cpus=4 --memory=8 --disk=40 \
  --set='.nestedVirtualization=true' \
  template:ubuntu-24.04
limactl list
limactl shell kvmhost
```

```
$ limactl list
NAME       STATUS     SSH                VMTYPE    ARCH       CPUS    MEMORY    DISK     DIR
kvmhost    Running    127.0.0.1:55668    vz        aarch64    4       8GiB      40GiB    ~/.lima/kvmhost
```

### 4.3. Диагностика внутри kvmhost

```bash
ls -l /dev/kvm
sudo apt update && sudo apt install -y cpu-checker && kvm-ok
```

```
$ ls -l /dev/kvm
crw-rw---- 1 root kvm 10, 232 Oct 20 06:39 /dev/kvm

$ kvm-ok
INFO: /dev/kvm exists
KVM acceleration can be used
```

---

## 5. Создание VM в KVM (вручную)

Все команды выполняются **внутри kvmhost** (`limactl shell kvmhost`).

### 5.1. Установка пакетов виртуализации

```bash
cd ~
sudo apt install -y qemu-system-arm qemu-efi-aarch64 qemu-utils \
                    libvirt-daemon-system virtinst cloud-image-utils
sudo virsh net-list --all      # сеть default (192.168.122.0/24, virbr0) должна быть active
```

### 5.2. Скачивание cloud-образа Ubuntu 24.04 arm64 и диск VM

Базовый образ не изменяется. Все изменения VM пишутся в отдельный overlay-диск `app-vm.qcow2` (backing file, 20G):

```bash
cd /var/lib/libvirt/images
sudo wget -q --show-progress https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img
sudo qemu-img create -f qcow2 -F qcow2 -b noble-server-cloudimg-arm64.img app-vm.qcow2 20G
cd ~
```

### 5.3. cloud-init: seed ISO с SSH-ключом

Lima монтирует домашнюю папку мака внутрь kvmhost, поэтому публичный ключ берётся прямо оттуда:

```bash
cat > ~/user-data <<EOF
#cloud-config
hostname: app-vm
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat /Users/egorkorostelev/.ssh/id_ed25519.pub)
EOF

cat > ~/meta-data <<'EOF'
instance-id: app-vm-01
local-hostname: app-vm
EOF

cat > ~/network-config <<'EOF'
version: 2
ethernets:
  id0:
    match:
      name: "en*"
    dhcp4: true
EOF

cloud-localds --network-config=network-config seed.iso user-data meta-data
sudo cp seed.iso /var/lib/libvirt/images/app-vm-seed.iso
```

### 5.4. Статический IP через DHCP-резервацию в сети default

```bash
sudo virsh net-update default add ip-dhcp-host \
  "<host mac='52:54:00:aa:bb:01' name='app-vm' ip='192.168.122.10'/>" --live --config
```

### 5.5. Создание VM через virt-install

```bash
sudo virt-install \
  --name app-vm --virt-type kvm \
  --memory 2048 --vcpus 2 \
  --arch aarch64 --machine virt --boot uefi \
  --disk path=/var/lib/libvirt/images/app-vm.qcow2,format=qcow2,bus=virtio \
  --disk path=/var/lib/libvirt/images/app-vm-seed.iso,device=cdrom \
  --osinfo linux2022 \
  --network network=default,model=virtio,mac=52:54:00:aa:bb:01 \
  --graphics none --import --noautoconsole

sudo virsh autostart app-vm     # VM стартует вместе с kvmhost
```

> **Почему seed ISO, а не `--cloud-init`.** Первая попытка была с `virt-install --cloud-init user-data=...`. VM создалась, но сразу оказалась в состоянии `shut off`. После ручного запуска она загрузилась как `ubuntu login:` без наших настроек: virt-install подключает данные cloud-init только на первый запуск, а он прервался. Поэтому VM была пересоздана (`virsh destroy`, `virsh undefine --nvram`, новый overlay-диск), а настройки подключены постоянным CD-ROM с NoCloud seed ISO. В консоли VM (`sudo virsh console app-vm`) cloud-init подтвердил источник `Datasource DataSourceNoCloud [seed=/dev/sr0]` и добавил ключ пользователю `ubuntu`, приглашение стало `app-vm login:`.

### 5.6. Проверка

```bash
sudo virsh list --all
sudo virsh dumpxml app-vm | grep "domain type"
sudo virsh domifaddr app-vm
```

```
$ sudo virsh list --all
 Id   Name     State
------------------------
 3    app-vm   running

$ sudo virsh dumpxml app-vm | grep "domain type"
<domain type='kvm' id='3'>

$ sudo virsh domifaddr app-vm
 Name       MAC address          Protocol     Address
-------------------------------------------------------------------------------
 vnet2      52:54:00:aa:bb:01    ipv4         192.168.122.10/24
```

`type='kvm'` означает аппаратное ускорение через `/dev/kvm`. При программной эмуляции QEMU TCG здесь было бы `type='qemu'`.

---

## 6. SSH-доступ к app-vm с ноутбука и проверка KVM изнутри

app-vm находится в изолированной сети libvirt, поэтому подключение к ней идёт через kvmhost (`ProxyJump`). Lima генерирует SSH-конфиг для kvmhost (хост `lima-kvmhost`).

`~/.ssh/config` на маке (строка `Include` стоит **в начале** файла, до любых блоков `Host`):

```
Include ~/.lima/kvmhost/ssh.config

Host app-vm
  HostName 192.168.122.10
  User ubuntu
  ProxyJump lima-kvmhost
```

Проверка с мака:

```
$ ssh app-vm 'hostname; systemd-detect-virt'
app-vm
kvm
```

---

## 7. Деплой приложения в VM и проброс порта

### 7.1. Установка Docker в app-vm

```bash
ssh app-vm 'sudo apt update && sudo apt install -y docker.io docker-compose-v2'
```

### 7.2. Копирование файлов и запуск

На маке, из каталога `lab2/`:

```bash
ssh app-vm 'mkdir -p ~/app'
scp -r backend frontend compose.yaml app-vm:~/app/
ssh app-vm 'cd ~/app && sudo docker compose up -d --build && sudo docker compose ps'
```

Образы собираются прямо в app-vm под arm64. Каталог проекта в VM называется `app`, поэтому контейнеры называются `app-backend-1` и `app-frontend-1`.

```
$ ssh app-vm 'cd ~/app && sudo docker compose ps'
NAME             IMAGE                 COMMAND                  SERVICE    CREATED        STATUS        PORTS
app-backend-1    lab-backend:latest    "gunicorn --bind 0.0…"   backend    13 hours ago   Up 13 hours   5000/tcp
app-frontend-1   lab-frontend:latest   "/docker-entrypoint.…"   frontend   13 hours ago   Up 13 hours   0.0.0.0:8080->80/tcp, [::]:8080->80/tcp

$ ssh app-vm 'curl -s localhost:8080/api/info'
{"container":"643440e21b61","message":"Привет от backend-сервиса на Flask!","time":"2026-10-20T08:20:43.782974+00:00"}
```

### 7.3. Проброс порта на ноутбук

Команда запускается **на маке** (не внутри kvmhost):

```bash
ssh -N -L 8080:localhost:8080 app-vm
```

Туннель открыт, пока команда работает. Порт `8080` на маке через kvmhost пробрасывается на `localhost:8080` внутри app-vm, где его слушает контейнер frontend.

> Перед запуском туннеля нужно остановить локальный стек (`docker compose down`), иначе порт 8080 на маке будет занят.

---

## 8. Адрес приложения

**http://localhost:8080**

Открывается в браузере на маке, пока работает туннель из п. 7.3.

---

## 9. Проверка связи фронтенда с бэкендом

1. **Страница в браузере.** На http://localhost:8080 видны сообщение, имя контейнера, время и исходный JSON из `/api/info`. Статус «Бэкенд доступен, данные получены» подтверждает, что `fetch` прошёл через nginx до Flask.

2. **curl с ноутбука через туннель:**

```
   $ curl localhost:8080/api/info
   {"container":"643440e21b61","message":"Привет от backend-сервиса на Flask!","time":"2026-10-20T08:22:16.082872+00:00"}
```

3. **Запрос дошёл именно до контейнера в app-vm.** Поле `container` (`643440e21b61`) с мака совпадает с ответом, полученным внутри app-vm в п. 7.2. Значит, запрос прошёл всю цепочку: ноутбук → SSH-туннель → kvmhost → app-vm → frontend (nginx) → backend (Flask).

4. **Бэкенд не опубликован наружу.** В `docker compose ps` у `backend` в колонке `PORTS` указано только `5000/tcp`, без `0.0.0.0:...`, то есть к нему можно обратиться только из сети compose через nginx.
