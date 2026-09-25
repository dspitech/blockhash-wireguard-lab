"""
BLOCKHash - Module directory
=========================================================
Provisioning VPN depuis un annuaire d'entreprise (Phase 1).

Ce paquet fournit une interface abstraite `DirectoryConnector`
(base.py) et des implementations concretes par famille de source
(actuellement : LDAP generique, couvrant AD local, OpenLDAP, Samba AD,
FreeIPA, JumpCloud LDAP, Azure AD DS et Google Secure LDAP - tous
compatibles avec le meme protocole LDAPS). `factory.get_connector()`
instancie le bon connecteur a partir de la configuration d'une source.

Etat d'avancement : voir README, section "Provisioning VPN depuis un
annuaire" pour le detail de ce qui est livre en Phase 1 et ce qui reste
sur la feuille de route (connecteurs API REST Microsoft Graph / Google
Workspace, politiques par groupe, synchronisation periodique, rollback,
etc.).
"""
