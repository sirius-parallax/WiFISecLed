Вот пошаговая инструкция «с чистого листа», чтобы на новой системе (например, Debian/Ubuntu-подобной) установить всё нужное и запустить твой `wifite-oled.py` как службу:

---

### 1. Обнови систему и установи необходимые пакеты
```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-pip git wifite util-linux \
                   python3-pil python3-pil.imagetk python3-pil.imagetk \
                   python3-setuptools python3-wheel \
                   i2c-tools libfreetype6-dev libjpeg-dev build-essential
```
- `wifite` — сам проводник по Wi-Fi.
- `util-linux` — для команды `script`.
- `python3-pil` и зависимые пакеты — для работы с OLED через `PIL`.
- `i2c-tools` — диагностика шин I²C, если понадобится.

Если в системе нет `pip`, оно уже через `python3-pip`.

---

### 2. Установи Python-зависимости для OLED и `luma`
```bash
sudo pip3 install --upgrade luma.oled pillow
```

---

### 3. Клонируй или положи скрипт

Создай директорию:
```bash
sudo mkdir -p /opt/wifi-audit
sudo chown $USER:$USER /opt/wifi-audit
```

Сохрани файл `wifite-oled.py` (тот полный скрипт, что мы обсуждали) в `/opt/wifi-audit/wifite-oled.py`. Убедись, что он исполняемый:
```bash
sudo cp wifite-oled.py /opt/wifi-audit/wifite-oled.py
sudo chmod +x /opt/wifi-audit/wifite-oled.py
```

---

### 4. Создай файл истории
```bash
sudo mkdir -p /var/lib
sudo touch /var/lib/wifite_history.json
sudo chmod 600 /var/lib/wifite_history.json
sudo chown root:root /var/lib/wifite_history.json
```

---

### 5. Проверь и настрой I²C
- Включи I²C, если на системе (например, NanoPi) нужно через `raspi-config` или вручную в `/boot/armbianEnv.txt`.
- Установи адрес дисплея, подключи проводкой.
- Убедись, что `i2cdetect -y 1` показывает `0x3C`.

---

### 6. Создай systemd-сервис

Создай файл `/etc/systemd/system/wifite-oled.service`:
```ini
[Unit]
Description=Wifite OLED auditor
After=network.target

[Service]
Type=simple
ExecStart=/opt/wifi-audit/wifite-oled.py
Restart=always
RestartSec=5
KillMode=process
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

### 7. Включи и запусти службу

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wifite-oled.service
```

Проверь статус:
```bash
sudo systemctl status wifite-oled.service
sudo journalctl -u wifite-oled.service -f
```

---

### 8. (Опционально) Настрой сеть

Если система автоматически запускает `NetworkManager`, можешь отключить управление Wi-Fi-интерфейсом:
```bash
sudo nmcli dev set wlan0 managed no
```
или, если интерфейс другой — подставь имя, которое выдаёт `ls /sys/class/net | grep '^wl' | head -1`.

---

### 9. Перезагрузка

После установки оборудование (включая OLED) должно работать автоматически. Перезагрузи систему, чтобы убедиться, что служба стартует при загрузке:
```bash
sudo reboot
```

---

### 10. Отладка

Если нужно вручную остановить/перезапустить:
```bash
sudo systemctl restart wifite-oled.service
sudo systemctl stop wifite-oled.service
```

Для чтения выводов (в том числе списка в консоли о ранее взломанных сетях):
```bash
sudo journalctl -u wifite-oled.service
```

---

### Дополнительно
- Убедись, что у пользователя `root` есть доступ к I²C и `wifite`.
- Если OLED требуется другой адрес/размер — поправь константы `OLED_ADDRESS`, `OLED_WIDTH`/`HEIGHT`.
- На `NanoPi` и других SBC может быть другая разметка `/boot/armbianEnv.txt`, проверь и включи `i2c1=on` и т. д.

---

Таким образом после этих действий у тебя будет полноценный сервис, который:
- запускается при старте системы,
- оборачивает `wifite` в TTY (через `script`),
- показывает историю и статус на OLED,
- сохраняет найденные ключи в `/var/lib/wifite_history.json`,
- автоматически перезапускается при падениях.

Если нужно — могу помочь сделать `install.sh`, который автоматизирует эти шаги.
