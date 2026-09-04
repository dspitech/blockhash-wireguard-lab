#cloud-config
package_update: true
package_upgrade: true
packages:
  - wireguard
  - wireguard-tools
  - qrencode
  - ufw
  - net-tools
  - python3
  - python3-pip
  - python3-venv
  - git
runcmd:
  - echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
  - sysctl -p
  - mkdir -p /etc/wireguard
  - chmod 700 /etc/wireguard
  - mkdir -p /opt/blockhash-lab
