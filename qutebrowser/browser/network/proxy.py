# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Handling of proxies."""

from typing import Optional

from qutebrowser.qt.core import pyqtSlot
from qutebrowser.qt.network import QNetworkProxy, QNetworkProxyFactory, QNetworkProxyQuery

from qutebrowser.config import config, configtypes


application_factory: Optional["ProxyFactory"] = None


def init():
    """Set the application wide proxy factory."""
    global application_factory
    application_factory = ProxyFactory()
    QNetworkProxyFactory.setApplicationProxyFactory(application_factory)


@pyqtSlot()
def shutdown():
    QNetworkProxyFactory.setApplicationProxyFactory(None)


class ProxyFactory(QNetworkProxyFactory):

    """Factory for proxies to be used by qutebrowser."""

    def _set_capabilities(self, proxy):
        if proxy.type() == QNetworkProxy.ProxyType.NoProxy:
            return

        # Send DNS requests over the proxy
        capabilities = proxy.capabilities()
        capabilities |= QNetworkProxy.Capability.HostNameLookupCapability
        proxy.setCapabilities(capabilities)

    def queryProxy(self, query: QNetworkProxyQuery = QNetworkProxyQuery()) -> list[QNetworkProxy]:
        """Get the QNetworkProxies for a query.

        Args:
            query: The QNetworkProxyQuery to get a proxy for.

        Return:
            A list of QNetworkProxy objects in order of preference.
        """
        proxy = config.val.content.proxy
        if proxy is configtypes.SYSTEM_PROXY:
            # On Linux, use "export http_proxy=socks5://host:port" to manually
            # set system proxy.
            # ref. https://doc.qt.io/qt-6/qnetworkproxyfactory.html#systemProxyForQuery
            proxies = QNetworkProxyFactory.systemProxyForQuery(query)
        else:
            proxies = [proxy]
        for proxy in proxies:
            self._set_capabilities(proxy)
        return proxies
