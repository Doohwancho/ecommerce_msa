# arm64 mysql:8.0.29에는 mysql-shell이 없음. 따라서 mysql-shell을 별도 설치한 커스텀 mysql을 사용한다.
FROM mysql:8.0.29

# 1. Add MySQL GPG key
RUN rpm --import https://repo.mysql.com/RPM-GPG-KEY-mysql-2023

# 2. Configure repository
RUN echo "[mysql-tools-community]" > /etc/yum.repos.d/mysql-community.repo \
 && echo "name=MySQL Tools Community" >> /etc/yum.repos.d/mysql-community.repo \
 && echo "baseurl=http://repo.mysql.com/yum/mysql-tools-community/el/8/aarch64/" >> /etc/yum.repos.d/mysql-community.repo \
 && echo "enabled=1" >> /etc/yum.repos.d/mysql-community.repo \
 && echo "gpgcheck=0" >> /etc/yum.repos.d/mysql-community.repo  # Temporarily disable GPG check

# 3. Create directories without trying to modify the systemd service file
RUN mkdir -p /usr/share/desktop-directories /etc/xdg/autostart

# 4. Install mysql-shell
RUN microdnf update -y \
 && microdnf install -y mysql-shell \
 && microdnf clean all