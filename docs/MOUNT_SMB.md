# Монтирование SMB-шары //192.168.10.153/vnedrenie/allm

Текущая рабочая конфигурация на a3linux (проверено 2026-11-12).

## 1. Факты с сервера

mount | grep -i allm:

    systemd-1 on /home/user/allm type autofs (...)
    //192.168.10.153/vnedrenie/allm on /home/user/allm type cifs (rw,relatime,vers=3.0,...)

grep allm /etc/fstab:

    //192.168.10.153/vnedrenie/allm  /home/user/allm  cifs  credentials=/etc/allm-cred,uid=1000,gid=1000,mfsymlinks,noauto,x-systemd.automount,_netdev,nofail,vers=3.0,iocharset=utf8  0  0

Ключевые моменты:
- autofs (x-systemd.automount) - монтирование по требованию
- noauto, nofail - не блокировать boot
- credentials=/etc/allm-cred - файл с логином/паролем (права 600 root:root)
- uid=1000,gid=1000 - файлы принадлежат пользователю user
- mfsymlinks - поддержка симв. ссылок
- vers=3.0 - SMB 3.0

## 2. Файл credentials

    sudo tee /etc/allm-cred >/dev/null <<CRED
    username=b.zhdanko
    password=<ПАРОЛЬ>
    domain=zkh
    CRED
    sudo chmod 600 /etc/allm-cred
    sudo chown root:root /etc/allm-cred

## 3. Строка в /etc/fstab

    //192.168.10.153/vnedrenie/allm  /home/user/allm  cifs  credentials=/etc/allm-cred,uid=1000,gid=1000,mfsymlinks,noauto,x-systemd.automount,_netdev,nofail,vers=3.0,iocharset=utf8  0  0

Применить без перезагрузки:

    sudo mkdir -p /home/user/allm
    sudo systemctl daemon-reload
    sudo systemctl restart remote-fs.target 2>/dev/null || true
    ls -la /home/user/allm | head

## 4. Проверка

    systemctl list-units --type=automount | grep allm
    mount | grep allm
    findmnt /home/user/allm
    ls -la /home/user/allm | head

## 5. Troubleshooting

- mount error(13): Permission denied - проверить /etc/allm-cred
- mount error(2): No such file - sudo mkdir -p /home/user/allm
- пусто в /home/user/allm - ls /home/user/allm (триггер autofs), затем systemctl restart remote-fs.target
- mount error(112): Host is down - ping 192.168.10.153

## 6. Что НЕ делает install_ivcrag.sh

Установщик не монтирует SMB автоматически. Только проверяет, что paths.docs_source существует.
