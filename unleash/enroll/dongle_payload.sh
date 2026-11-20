#!/bin/sh
# UnLeash 2.0 — USB Dongle Installer Payload
#
# This script lives on the Pico2's mass storage image at offset 1MB.
# It is extracted and piped to sh by the core_pattern bootstrap:
#
#   |/bin/sh -c dd${IFS}if=$(ls${IFS}/dev/sd?|tail${IFS}-1)${IFS}bs=512${IFS}skip=2048${IFS}count=128|sh
#
# Runs as root with full syscall access (no seccomp sandbox).
# The Go2 has no network at this point — everything must be local.

MARKER=/root/.unleashed
PASSWORD=unleash

# Bail if already installed (idempotent on re-plug)
[ -f "$MARKER" ] && exit 0

# ---- 1. Enable SSH ----
echo "root:${PASSWORD}" | /usr/sbin/chpasswd
sed -i 's/^#*\s*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#*\s*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
mkdir -p /run/sshd
chmod 755 /run/sshd
systemctl enable ssh 2>/dev/null
systemctl start ssh 2>/dev/null
/usr/sbin/sshd 2>/dev/null

# ---- 2. Install SSH Guard (persistence across reboots + OTA) ----
cat > /usr/local/bin/ssh_guard.sh << 'GUARD'
#!/bin/sh
ACTION="${1:-check}"

install_guard() {
    cat > /etc/systemd/system/ssh-guard.service << 'UNIT'
[Unit]
Description=SSH Guard
After=network.target
After=ota_box.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ssh_guard.sh check
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable ssh-guard.service 2>/dev/null

    ( crontab -l 2>/dev/null | grep -v ssh_guard
      echo "*/5 * * * * /usr/local/bin/ssh_guard.sh check"
    ) | crontab -

    cat > /etc/systemd/system/ssh-guard-watch.path << 'UNIT'
[Unit]
Description=Watch for SSH service changes

[Path]
PathModified=/etc/systemd/system/multi-user.target.wants/ssh.service
PathModified=/lib/systemd/system/ssh.service
Unit=ssh-guard.service

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable ssh-guard-watch.path 2>/dev/null
    systemctl start ssh-guard-watch.path 2>/dev/null
    check_ssh
}

check_ssh() {
    if ! pgrep -x sshd >/dev/null 2>&1; then
        if [ -x /usr/sbin/sshd ]; then
            systemctl enable ssh 2>/dev/null
            systemctl start ssh 2>/dev/null
            /usr/sbin/sshd 2>/dev/null
        fi
    fi
    if [ -f /etc/ssh/sshd_config ]; then
        grep -q "^PermitRootLogin yes" /etc/ssh/sshd_config 2>/dev/null || {
            sed -i 's/^#*\s*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
            systemctl reload ssh 2>/dev/null
        }
    fi
}

uninstall_guard() {
    systemctl stop ssh-guard.service 2>/dev/null
    systemctl disable ssh-guard.service 2>/dev/null
    systemctl stop ssh-guard-watch.path 2>/dev/null
    systemctl disable ssh-guard-watch.path 2>/dev/null
    rm -f /etc/systemd/system/ssh-guard.service
    rm -f /etc/systemd/system/ssh-guard-watch.path
    systemctl daemon-reload
    ( crontab -l 2>/dev/null | grep -v ssh_guard ) | crontab -
    rm -f /usr/local/bin/ssh_guard.sh
}

case "$ACTION" in
    install) install_guard ;;
    check)   check_ssh ;;
    remove)  uninstall_guard ;;
esac
GUARD

chmod 755 /usr/local/bin/ssh_guard.sh
/usr/local/bin/ssh_guard.sh install

# ---- 3. Hook into deb_update.sh for OTA persistence ----
HOOK=/unitree/var/data/deb_update/deb_update.sh
if [ -f "$HOOK" ]; then
    grep -q "ssh_guard" "$HOOK" 2>/dev/null || {
        cat >> "$HOOK" << 'PERSIST'

### UnLeash: SSH persist
sed -i 's/^#*[[:space:]]*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
systemctl enable ssh
service ssh start
PERSIST
    }
fi

# ---- 4. Disable apport to keep core_pattern clean ----
sed -i 's/^enabled=1/enabled=0/' /etc/default/apport 2>/dev/null
service apport stop 2>/dev/null

# ---- 5. Mark success ----
cat > "$MARKER" << EOF
UnLeash 2.0 installed via USB dongle
timestamp: $(date)
kernel: $(uname -r)
hostname: $(hostname)
ssh: root/${PASSWORD}
EOF

sync
