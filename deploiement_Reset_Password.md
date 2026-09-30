# Installation du projet

## 1. Préparation de Terraform
Cloner le dépôt et préparer le fichier de configuration Terraform :


```PowerShell
git clone https://github.com/dspitech/blockhash-wireguard-lab.git && cd blockhash-wireguard-lab/terraform && cp terraform.tfvars.example terraform.tfvars
```

## 2. Configuration et changement d'IP publique  > terraform.tfvars
Formater, initialiser, valider et appliquer l'infrastructure Terraform :

```PowerShell
terraform fmt && terraform init && terraform validate && terraform plan && terraform apply -auto-approve
```

## 3. Connexion SSH au serveur
Une fois l'infrastructure déployée, se connecter au serveur :


```PowerShell
ssh wgadmin@20.251.112.149
```

## 4. Installation de WireGuard
Cloner le dépôt sur le serveur, rendre les scripts exécutables puis lancer l'installation de WireGuard :

```bash
git clone https://github.com/dspitech/blockhash-wireguard-lab.git && cd blockhash-wireguard-lab/scripts && chmod +x *.sh && sudo ./01-install-wireguard-server.sh
```

## 5. Installation du Dashboard
Accéder au répertoire du projet :

```bash
cd ~/blockhash-wireguard-lab
```

Installer le Dashboard sur le port 8080 :

```bash
sudo ./scripts/03-install-dashboard.sh 8080
```

## 6. Logging et Monitoring
Installer le système de journalisation et de supervision :

```bash
sudo ./04-logging-monitoring.sh
```

---

# Réinitialisation du mot de passe admin

## Étape 1 - Générer un mot de passe et son hash

```bash
NEW_PASS=$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)
NEW_HASH=$(sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 -c "
from werkzeug.security import generate_password_hash
print(generate_password_hash('$NEW_PASS', method='scrypt'))
")
echo ""
echo "======================================================"
echo "  MOT DE PASSE : $NEW_PASS"
echo "======================================================"
```

## Étape 2 - Mettre à jour la base SQLite


```bash
sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 << EOF
import sqlite3
conn = sqlite3.connect('/var/log/wireguard/blockhash.db')
cur = conn.execute(
    "UPDATE users SET password_hash = ? WHERE username = 'admin'",
    ('$NEW_HASH',)
)
conn.commit()
print("Lignes modifiées :", cur.rowcount)
EOF
```

## Étape 3 - Redémarrer le service


```bash
sudo systemctl restart blockhash-dashboard
sleep 3
sudo systemctl status blockhash-dashboard --no-pager | head -5
```

## Étape 4 - Vérifier que le hash correspond bien au mot de passe


```bash
read -rsp "Mot de passe à tester : " TEST_PWD; echo
sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 - "$TEST_PWD" << 'EOF'
import sqlite3, sys
from werkzeug.security import check_password_hash

pwd = sys.argv[1]
conn = sqlite3.connect('/var/log/wireguard/blockhash.db')
h = conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
print("Hash en base :", h[:50] + "...")
print("Match :", check_password_hash(h, pwd))
EOF
```

Vous devez voir **Match : True**. Si vous voyez **False**, l'étape 2 a échoué - recommencez.

---

## Etape 5 - Nettoyage après réinitialisation
Après une réinitialisation, il est recommandé de nettoyer les traces de l'ancien mot de passe :


```bash
# Supprimer les sauvegardes du fichier env
sudo rm -f /etc/blockhash/dashboard.env.bak*
sudo rm -f /etc/blockhash/dashboard.env.old

# Invalider les sessions actives (force la reconnexion partout)
sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('/var/log/wireguard/blockhash.db')
try:
    conn.execute('DELETE FROM sessions')
    conn.commit()
    print('Sessions supprimées.')
except sqlite3.OperationalError:
    print('Table sessions absente, rien à faire.')
"

# Vérifier les permissions du fichier env
sudo chmod 640 /etc/blockhash/dashboard.env
sudo chown root:root /etc/blockhash/dashboard.env
```

## Réinitialiser un autre utilisateur
Remplacez 'admin' par le nom d'utilisateur cible dans la requête UPDATE :


```bash
TARGET_USER="nom_utilisateur"

NEW_PASS=$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)
NEW_HASH=$(sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 -c "
from werkzeug.security import generate_password_hash
print(generate_password_hash('$NEW_PASS', method='scrypt'))
")

sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 << EOF
import sqlite3
conn = sqlite3.connect('/var/log/wireguard/blockhash.db')
cur = conn.execute(
    "UPDATE users SET password_hash = ? WHERE username = ?",
    ('$NEW_HASH', '$TARGET_USER')
)
conn.commit()
print("Lignes modifiées :", cur.rowcount)
EOF

echo "Nouveau mot de passe pour $TARGET_USER : $NEW_PASS"
```

## Lister tous les utilisateurs
Avant toute réinitialisation, il est utile de vérifier qui existe réellement :

```bash
sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 << 'EOF'
import sqlite3
from datetime import datetime

conn = sqlite3.connect('/var/log/wireguard/blockhash.db')
print(f"{'Username':<20} {'Rôle':<10} {'Actif':<6} {'Créé':<20} {'Dernier login':<20}")
print("-" * 80)
for row in conn.execute("SELECT username, role, active, created_ts, last_login_ts FROM users"):
    username, role, active, created, last = row
    created_str = datetime.fromtimestamp(created).strftime('%Y-%m-%d %H:%M') if created else '-'
    last_str = datetime.fromtimestamp(last).strftime('%Y-%m-%d %H:%M') if last else 'jamais'
    print(f"{username:<20} {role:<10} {'oui' if active else 'non':<6} {created_str:<20} {last_str:<20}")
EOF
```


## Créer un nouvel administrateur
Si aucun compte admin n'est accessible, créez-en un nouveau :

```bash
NEW_USER="admin-secours"
NEW_PASS=$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)
NEW_HASH=$(sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 -c "
from werkzeug.security import generate_password_hash
print(generate_password_hash('$NEW_PASS', method='scrypt'))
")

sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 << EOF
import sqlite3, time
conn = sqlite3.connect('/var/log/wireguard/blockhash.db')
conn.execute(
    "INSERT INTO users (username, password_hash, role, active, created_ts) VALUES (?, ?, 'admin', 1, ?)",
    ('$NEW_USER', '$NEW_HASH', int(time.time()))
)
conn.commit()
print("Utilisateur '$NEW_USER' créé avec le rôle admin.")
EOF

echo ""
echo "Nouvel admin : $NEW_USER"
echo "Mot de passe : $NEW_PASS"
```

## Désactiver un utilisateur (sans le supprimer)
Pour bloquer un compte sans perdre son historique :

```bash
TARGET_USER="nom_utilisateur"

sudo -u www-data /opt/blockhash-dashboard/venv/bin/python3 << EOF
import sqlite3
conn = sqlite3.connect('/var/log/wireguard/blockhash.db')
cur = conn.execute("UPDATE users SET active = 0 WHERE username = ?", ('$TARGET_USER',))
conn.commit()
print("Lignes modifiées :", cur.rowcount)
EOF
```


Pour le réactiver, remplacez **active = 0** par **active = 1**.

## Cas particuliers
Le service ne démarre pas
Consultez les logs :


```bash
sudo journalctl -u blockhash-dashboard -n 50 --no-pager
```

