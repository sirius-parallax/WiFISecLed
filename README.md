
---

### 1. Установи зависимости

```bash
sudo apt update
sudo apt install -y python3-pip python3-pil git build-essential libatlas-base-dev wiringpi
sudo pip3 install luma.oled
```

Если дисплей I²C, убедись, что включён в `raspi-config`‑аналогe или `/boot/armbianEnv.txt`.

---

### 2. Склонируй/подготовь проект

```bash
sudo mkdir -p /opt/wifi-audit
sudo chown "$USER":"$USER" /opt/wifi-audit
cd /opt/wifi-audit
# здесь могут быть дополнительные файлы, например скрипты установки
```

---

### 3. Запиши основной скрипт

```bash
sudo tee /usr/local/bin/wifite-oled.py >/dev/null <<'EOF'
#!/usr/bin/env python3
ТУТ САМ СКРИПТ
EOF
sudo chmod +x /usr/local/bin/wifite-oled.py
```

*(Убедись, что вставляешь весь код из последнего ответа — в том числе с функцией `wifite_status_reader`, которая очищает ANSI-коды.)*

---

### 4. Создай systemd-сервис

```bash
sudo tee /etc/systemd/system/wifite-oled.service >/dev/null <<'EOF'
[Unit]
Description=Wifite OLED auditor
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/wifite-oled.py
Restart=on-failure
KillMode=control-group
WorkingDirectory=/opt/wifi-audit
StandardOutput=journal
StandardError=inherit

[Install]
WantedBy=multi-user.target
EOF
```

---

### 5. Применить и запустить сервис

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wifite-oled.service
sudo journalctl -u wifite-oled.service -f
```

---

### 6. (опционально) Управление

- **Остановить:** `sudo systemctl stop wifite-oled.service`
- **Перезапустить:** `sudo systemctl restart wifite-oled.service`
- **Проверить статус:** `sudo systemctl status wifite-oled.service`

---

### 7. Сохраняем историю взломанных сетей

Скрипт пишет `/var/lib/wifite_history.json`. Убедись, что папка доступна:

```bash
sudo mkdir -p /var/lib
sudo chown root:root /var/lib
sudo touch /var/lib/wifite_history.json
sudo chmod 600 /var/lib/wifite_history.json
```

---

### 8. Итого

- Скрипт читает `wifite` через PTY, пилит OLED-интерфейс и фильтрует вывод в систему логов.
- Юнит `KillMode=control-group` гарантирует, что `wifite`, `reaver` и другие дочерние процессы убиваются при остановке.
- В логах `journalctl -u wifite-oled.service` будет чистый текст без `[xxxB blob data]`.

