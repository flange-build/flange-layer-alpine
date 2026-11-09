// 打印 libc 类型、线程与 zlib 版本：glibc 编译的程序在 musl 上无法加载，
// 能运行并输出 libc=musl 即说明工具链、SDK 与 apk 依赖一致。
#include <iostream>
#include <string>
#include <thread>

#include <zlib.h>

int main()
{
#ifdef __GLIBC__
	const char *libc = "glibc";
#else
	const char *libc = "musl";
#endif
	std::string worker;
	std::thread thread([&worker] { worker = "ok"; });
	thread.join();
	std::cout << "musl-check: libc=" << libc << " thread=" << worker
		  << " zlib=" << zlibVersion() << std::endl;
	return 0;
}
