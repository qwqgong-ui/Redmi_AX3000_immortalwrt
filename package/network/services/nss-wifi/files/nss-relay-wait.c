#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <time.h>

/* BusyBox on this target has integer-only sleep. Poll quickly only while
 * waiting for the first M1, otherwise the watcher retains its one-second tick.
 */
int main(void)
{
	struct timespec delay = { .tv_sec = 0, .tv_nsec = 250000000 };

	while (nanosleep(&delay, &delay))
		if (errno != EINTR)
			return 1;
	return 0;
}
