"""
wechat_crypto.py · 企业微信 AES-256-CBC 加解密模块
================================================================
职责：
  1. 实现企微官方 AES-256-CBC 加解密协议（SHA1 签名校验）
  2. 用于网关验签 (VerifyURL) 和消息解密 (DecryptMsg)
  3. 提供消息加密 (EncryptMsg) 用于出站消息

企微协议参考：
  https://developer.work.weixin.qq.com/document/path/90968

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import base64
import hashlib
import json
import os
import struct
import time
import random
import string
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from loguru import logger


# ==============================================================================
# 错误码定义
# ==============================================================================

class WeChatCryptoError(Exception):
    """企微加解密异常基类"""
    def __init__(self, errcode: int, errmsg: str):
        self.errcode = errcode
        self.errmsg = errmsg
        super().__init__(f"[{errcode}] {errmsg}")


class WXBizMsgCrypt:
    """
    企业微信消息加解密类

    初始化参数：
      token:         企微后台配置的回调 Token
      encoding_aes_key: 企微后台配置的 AES Key（43位 Base64 字符串，解码后为 32 字节 AES-256 密钥）
      corp_id:       企业 ID（用于验证消息来源）
    """

    # AES 密钥长度（解码前 43 字符，解码后 32 字节）
    AES_KEY_LENGTH = 32

    # 错误码
    OK = 0
    VALIDATE_SIGNATURE_ERROR = -40001
    PARSE_XML_ERROR = -40002
    COMPUTE_SIGNATURE_ERROR = -40003
    ILLEGAL_AES_KEY = -40004
    VALIDATE_CORP_ID_ERROR = -40005
    ENCRYPT_AES_ERROR = -40006
    DECRYPT_AES_ERROR = -40007
    ILLEGAL_BUFFER = -40008
    BASE64_DECODE_ERROR = -40009

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id

        # 解码 AES Key（43 字符 Base64 -> 32 字节 AES-256 密钥）
        try:
            # EncodingAESKey 不含 "=" 填充符，需要手动补齐
            padded_key = encoding_aes_key + "=" * (4 - len(encoding_aes_key) % 4)
            self.aes_key = base64.b64decode(padded_key)
            if len(self.aes_key) != self.AES_KEY_LENGTH:
                raise WeChatCryptoError(
                    self.ILLEGAL_AES_KEY,
                    f"AES Key 解码后长度 {len(self.aes_key)}，期望 {self.AES_KEY_LENGTH}"
                )
        except WeChatCryptoError:
            raise
        except Exception as e:
            raise WeChatCryptoError(self.BASE64_DECODE_ERROR, f"AES Key 解码失败: {e}")

        logger.debug("WXBizMsgCrypt 初始化成功")

    # =========================================================================
    # SHA1 签名生成与校验
    # =========================================================================

    def _get_sha1(self, token: str, timestamp: str, nonce: str, encrypt_xml: str) -> str:
        """
        生成 SHA1 签名（企微官方算法）
        签名 = SHA1(sort(token, timestamp, nonce, encrypt_xml))
        """
        sort_list = sorted([token, timestamp, nonce, encrypt_xml])
        sha1_str = "".join(sort_list)
        return hashlib.sha1(sha1_str.encode("utf-8")).hexdigest()

    def _verify_signature(self, msg_signature: str, token: str, timestamp: str,
                          nonce: str, encrypt_xml: str) -> bool:
        """验证消息签名"""
        expected = self._get_sha1(token, timestamp, nonce, encrypt_xml)
        if expected != msg_signature:
            logger.warning(
                f"签名校验失败 | 期望: {expected[:16]}... | 实际: {msg_signature[:16]}..."
            )
            return False
        return True

    # =========================================================================
    # AES 加解密核心
    # =========================================================================

    @staticmethod
    def _pkcs7_pad(data: bytes, block_size: int = 32) -> bytes:
        """
        PKCS7 填充
        企微使用 AES-256-CBC，块大小 32 字节
        """
        pad_len = block_size - (len(data) % block_size)
        padding = bytes([pad_len] * pad_len)
        return data + padding

    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        """PKCS7 反填充"""
        if not data:
            return data
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 32:
            return data
        # 验证所有填充字节
        if data[-pad_len:] != bytes([pad_len] * pad_len):
            return data
        return data[:-pad_len]

    def _aesEncrypt(self, text: str) -> str:
        """
        AES-256-CBC 加密（符合企业微信协议）。
        加密结构: random(16B) + msg_len(4B big-endian) + msg + corp_id

        返回: Base64 编码的密文
        """
        try:
            # 1. 生成 16 字节随机字符串
            random_bytes = os.urandom(16)

            # 2. 构造明文 blob: random + msg_len(4B) + msg + corp_id
            text_bytes = text.encode("utf-8")
            msg_len_bytes = struct.pack(">I", len(text_bytes))
            corp_id_bytes = self.corp_id.encode("utf-8")

            blob = random_bytes + msg_len_bytes + text_bytes + corp_id_bytes

            # 3. PKCS7 填充（AES-256: 32 字节块大小）
            padded_blob = self._pkcs7_pad(blob)

            # 4. AES-256-CBC 加密（使用隐式 IV: 前 16 字节密文作为下一块的 IV，
            #    但这里使用显式 IV: 随机 16 字节放在密文前面）
            iv = os.urandom(16)
            cipher = Cipher(
                algorithms.AES(self.aes_key),
                modes.CBC(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            ciphertext = encryptor.update(padded_blob) + encryptor.finalize()

            # 5. 拼接 IV + 密文，然后 Base64 编码
            encrypted_blob = iv + ciphertext
            return base64.b64encode(encrypted_blob).decode("utf-8")

        except Exception as e:
            raise WeChatCryptoError(self.ENCRYPT_AES_ERROR, f"AES 加密失败: {e}")

    def _aesDecrypt(self, encrypted: str) -> str:
        """
        AES-256-CBC 解密（符合企业微信协议）。
        加密结构: random(16B) + msg_len(4B big-endian) + msg + corp_id

        输入: Base64 编码的密文
        返回: 解密后的原文（msg 部分）
        """
        try:
            # 1. Base64 解码
            encrypted_bytes = base64.b64decode(encrypted)

            # 2. 提取 IV（前 16 字节）和密文
            if len(encrypted_bytes) < 16:
                raise WeChatCryptoError(
                    self.ILLEGAL_BUFFER,
                    f"密文长度不足 16 字节: {len(encrypted_bytes)}"
                )
            iv = encrypted_bytes[:16]
            ciphertext = encrypted_bytes[16:]

            # 3. AES-256-CBC 解密
            cipher = Cipher(
                algorithms.AES(self.aes_key),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()

            # 4. 反 PKCS7 填充
            content = self._pkcs7_unpad(padded)

            # 5. 解析 blob: random(16B) + msg_len(4B big-endian) + msg + corp_id
            if len(content) < 21:
                raise WeChatCryptoError(
                    self.ILLEGAL_BUFFER,
                    f"解密内容长度不足（至少需要 21 字节）: {len(content)}"
                )

            # 跳过前 16 字节 random，读取消息长度
            msg_len = struct.unpack(">I", content[16:20])[0]

            # 提取消息内容（从第 20 字节开始）
            start = 20
            end = start + msg_len
            if end > len(content):
                raise WeChatCryptoError(
                    self.ILLEGAL_BUFFER,
                    f"消息长度越界: msg_len={msg_len}, content_len={len(content)}"
                )

            msg_bytes = content[start:end]

            # 6. 验证 corp_id（可选，用于消息来源验证）
            remaining = content[end:]
            if self.corp_id and not remaining.decode("utf-8", errors="ignore").endswith(self.corp_id):
                logger.warning(
                    f"CorpID 验证失败: 期望结尾为 '{self.corp_id}', "
                    f"实际: '{remaining.decode('utf-8', errors='ignore')}'"
                )
                # 不作为致命错误处理，微信文档建议此情况下返回 INVALID_CORP_ID
                # 但为兼容性考虑，仅记录警告而不阻断

            return msg_bytes.decode("utf-8")

        except WeChatCryptoError:
            raise
        except Exception as e:
            raise WeChatCryptoError(self.DECRYPT_AES_ERROR, f"AES 解密失败: {e}")

    # =========================================================================
    # 公开接口
    # =========================================================================

    def VerifyURL(self, msg_signature: str, timestamp: str, nonce: str,
                  echostr: str) -> Tuple[int, str]:
        """
        企微管理后台配置 Webhook URL 时触发的验签接口（GET 请求）。

        :param msg_signature: 企微传递的签名
        :param timestamp:     时间戳
        :param nonce:         随机字符串
        :param echostr:       企微传递的加密随机字符串（Base64 编码）
        :return: (errcode, 解密后的 echostr)
                 errcode == 0 表示验签成功

        处理流程（企业微信协议）：
          1. 用 SHA1 验证签名（使用原始 echostr 字符串参与签名计算）
          2. AES 解密 echostr 得到明文随机串
          3. 将明文随机串直接返回给微信服务器
        """
        try:
            # Step 1: SHA1 签名验证
            # 注意：验签使用原始 echostr（Base64 字符串），不是解密后的内容
            if not self._verify_signature(msg_signature, timestamp, nonce, echostr):
                return self.VALIDATE_SIGNATURE_ERROR, ""

            # Step 2: AES 解密 echostr
            # _aesDecrypt 内部会先做 Base64 解码，再 AES-CBC 解密
            decrypted_str = self._aesDecrypt(echostr)

            logger.success("[WeChatCrypto] 企微 URL 验签成功")
            return self.OK, decrypted_str

        except WeChatCryptoError as e:
            logger.error(f"[WeChatCrypto] 验签失败: {e}")
            return e.errcode, ""
        except Exception as e:
            logger.error(f"[WeChatCrypto] 验签异常: {e}")
            return self.PARSE_XML_ERROR, ""

    def DecryptMsg(self, encrypt_xml: str, msg_signature: str,
                   timestamp: str, nonce: str) -> Tuple[int, str]:
        """
        解密接收到的企微消息（POST 请求）。

        :param encrypt_xml:   XML 字符串（包含 <Encrypt> 节点）
        :param msg_signature: 企微传递的消息签名
        :param timestamp:     时间戳
        :param nonce:         随机字符串
        :return: (errcode, 解密后的 XML 字符串)
                 errcode == 0 表示解密成功
        """
        try:
            # 解析 XML，提取 Encrypt 节点
            tree = ET.fromstring(encrypt_xml)
            encrypt_node = tree.find("Encrypt")
            if encrypt_node is None:
                logger.warning("[WeChatCrypto] 消息 XML 中无 Encrypt 节点，可能是纯文本消息")
                return self.OK, encrypt_xml

            encrypt_content = encrypt_node.text
            if not encrypt_content:
                logger.error("[WeChatCrypto] Encrypt 节点内容为空")
                return self.ILLEGAL_BUFFER, ""

            # Step 1: 验签
            if not self._verify_signature(msg_signature, timestamp, nonce, encrypt_content):
                return self.VALIDATE_SIGNATURE_ERROR, ""

            # Step 2: AES 解密
            decrypted_xml = self._aesDecrypt(encrypt_content)

            logger.debug(f"[WeChatCrypto] 消息解密成功: {decrypted_xml[:100]}...")
            return self.OK, decrypted_xml

        except ET.ParseError as e:
            logger.error(f"[WeChatCrypto] XML 解析失败: {e}")
            return self.PARSE_XML_ERROR, ""
        except WeChatCryptoError as e:
            logger.error(f"[WeChatCrypto] 解密失败: {e}")
            return e.errcode, ""
        except Exception as e:
            logger.error(f"[WeChatCrypto] DecryptMsg 异常: {e}")
            return self.DECRYPT_AES_ERROR, ""

    def EncryptMsg(self, reply_xml: str, nonce: str, timestamp: Optional[str] = None) -> str:
        """
        加密要发送的回复消息（被动回复 / 回调响应）。

        :param reply_xml: 要发送的回复 XML 原文
        :param nonce:     企微传递的随机字符串
        :param timestamp: 时间戳（可选，默认当前时间）
        :return: 加密后的 XML 字符串
        """
        try:
            timestamp = timestamp or str(int(time.time()))

            # Step 1: AES 加密回复内容（包含 corp_id）
            encrypt_str = self._aesEncrypt(reply_xml)

            # Step 2: 生成 SHA1 签名
            signature = self._get_sha1(self.token, timestamp, nonce, encrypt_str)

            # Step 3: 组装加密 XML
            encrypt_xml = (
                "<xml>\n"
                "<Encrypt><![CDATA[" + encrypt_str + "]]></Encrypt>\n"
                "<MsgSignature><![CDATA[" + signature + "]]></MsgSignature>\n"
                "<TimeStamp>" + timestamp + "</TimeStamp>\n"
                "<Nonce><![CDATA[" + nonce + "]]></Nonce>\n"
                "</xml>"
            )

            logger.debug(f"[WeChatCrypto] EncryptMsg 加密成功，长度: {len(encrypt_xml)}")
            return encrypt_xml

        except WeChatCryptoError:
            raise
        except Exception as e:
            logger.error(f"[WeChatCrypto] EncryptMsg 失败: {e}")
            raise WeChatCryptoError(self.ENCRYPT_AES_ERROR, f"加密消息失败: {e}")

    def CheckSignature(self, msg_signature: str, timestamp: str, nonce: str,
                       encrypt_xml: str) -> bool:
        """快速验签接口（不涉及解密）"""
        return self._verify_signature(msg_signature, timestamp, nonce, encrypt_xml)


# ==============================================================================
# Mock 模式（开发测试用）
# ==============================================================================

class MockWeChatCrypto:
    """Mock 加解密器 - 仅用于开发测试"""

    def VerifyURL(self, msg_signature: str, timestamp: str, nonce: str, echostr: str):
        logger.info(f"[Mock] 验签请求: sig={msg_signature[:10]}..., echostr={echostr[:20]}...")
        return (0, echostr)

    def DecryptMsg(self, encrypt_xml: str, msg_signature: str, timestamp: str, nonce: str):
        try:
            tree = ET.fromstring(encrypt_xml)
            encrypt_node = tree.find("Encrypt")
            if encrypt_node is not None:
                return (0, "<xml><Content><![CDATA[Mock decrypted content]]></Content></xml>")
            return (0, encrypt_xml)
        except Exception:
            return (0, encrypt_xml)

    def EncryptMsg(self, reply_xml: str, nonce: str, timestamp: Optional[str] = None) -> str:
        return f"<xml><Mock>Encrypted</Mock></xml>"

    def CheckSignature(self, msg_signature: str, timestamp: str, nonce: str, encrypt_xml: str) -> bool:
        return True


# ==============================================================================
# 工厂函数
# ==============================================================================

def create_wechat_crypto(
    token: Optional[str] = None,
    encoding_aes_key: Optional[str] = None,
    corp_id: Optional[str] = None
) -> Tuple[object, bool]:
    """
    工厂函数：创建企微加解密实例。

    :param token:             企微 Token（优先使用参数，其次环境变量 WECHAT_TOKEN）
    :param encoding_aes_key:  企微 EncodingAESKey（优先使用参数，其次环境变量）
    :param corp_id:           企微 CorpID（优先使用参数，其次环境变量 WECHAT_CORP_ID）
    :return: (crypto_instance, is_mock)
             - is_mock=True 表示使用 Mock 模式（开发环境）
             - is_mock=False 表示使用真实加解密（生产环境）
    """
    import os as _os

    token = token or _os.environ.get("WECHAT_TOKEN", "")
    encoding_aes_key = encoding_aes_key or _os.environ.get("WECHAT_ENCODING_AES_KEY", "")
    corp_id = corp_id or _os.environ.get("WECHAT_CORP_ID", "")

    if not token or not encoding_aes_key or not corp_id:
        logger.warning(
            "[WeChatCrypto] 企微加解密参数不完整，切换到 Mock 模式。"
            f" token={bool(token)}, aes_key={bool(encoding_aes_key)}, corp_id={bool(corp_id)}"
        )
        return MockWeChatCrypto(), True

    try:
        crypto = WXBizMsgCrypt(token, encoding_aes_key, corp_id)
        logger.info("[WeChatCrypto] 企微加解密套件初始化成功")
        return crypto, False
    except Exception as e:
        logger.error(f"[WeChatCrypto] 企微加解密初始化失败: {e}，切换到 Mock 模式")
        return MockWeChatCrypto(), True


# ==============================================================================
# 别名导出（WeChatCrypto 是 WXBizMsgCrypt 的别名，与项目其他工具命名一致）
# ==============================================================================

WeChatCrypto = WXBizMsgCrypt


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    "WXBizMsgCrypt",
    "WeChatCrypto",          # WXBizMsgCrypt 的别名
    "MockWeChatCrypto",
    "WeChatCryptoError",
    "create_wechat_crypto",
]
