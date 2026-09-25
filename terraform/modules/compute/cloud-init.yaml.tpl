#cloud-config
# NOTE - needrestart : Ubuntu affiche par defaut une invite interactive
# (whiptail) des qu'un paquet upgrade/installe necessite un redemarrage de
# service (quasi systematique avec package_upgrade: true ci-dessous, qui met
# a jour libc/openssl et consorts). Sur une session SSH non-interactive
# (Terraform remote-exec, Ansible, etc.), cette invite ne recoit jamais de
# reponse : la commande semble ne jamais se terminer et la session SSH ne
# rend pas la main - meme si tout le reste du deploiement a reussi entre
# temps. Symptome typique : "null_resource.deploy: Still creating..."
# indefiniment, puis a l'interruption manuelle,
# "remote command exited without exit status or exit signal".
# `write_files` s'execute avant le module `packages`/`package_upgrade` dans
# l'ordonnancement de cloud-init : le correctif est donc en place AVANT la
# toute premiere mise a jour de paquets, plutot que via `runcmd` (trop tard).
write_files:
  - path: /etc/needrestart/conf.d/50-blockhash-noninteractive.conf
    owner: root:root
    permissions: '0644'
    content: |
      # Mode automatique : redemarre les services concernes sans invite
      # interactive (voir note ci-dessus). Documente egalement dans le
      # README, section deploiement / depannage.
      $nrconf{restart} = 'a';
      $nrconf{ucodeage} = 0;
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
