#pragma once
#include <cstddef>
extern "C" unsigned char* SHA256(const unsigned char*,size_t,unsigned char*);
inline int mbedtls_sha256(const unsigned char* bytes,size_t size,unsigned char out[32],int){return SHA256(bytes,size,out)?0:-1;}
