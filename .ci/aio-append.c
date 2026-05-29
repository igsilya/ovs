/*
 * FreeBSD aio_write() O_APPEND ordering reproducer.
 *
 * Submits many concurrent aio_write() operations on an O_APPEND file
 * descriptor.  Each line contains a sequence number followed by a fill
 * character ('A' or 'B', alternating).  Verifies that:
 *
 *   1. Lines are not reordered (sequence numbers are monotonically
 *      increasing in the output file).
 *   2. Lines are not interleaved (all fill characters on a line are
 *      the same).
 *
 * Per FreeBSD aio_write(2):
 *   "If O_APPEND is set for iocb->aio_fildes, write operations
 *    append to the file in the same order as the calls were made."
 *
 * Build:  cc -o aio-append aio-append.c       (FreeBSD)
 *         cc -o aio-append aio-append.c -lrt   (Linux)
 * Run:    ./aio-append
 */

#include <aio.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define LINE_LEN   200   /* Total line length (excluding newline). */
#define PREFIX_LEN 9     /* "00000001 " -- seq number + space. */
#define MAX_CBS    256   /* In-flight aiocb ring size. */
#define N_WRITES   50000 /* Total aio_write() calls. */

static void
drain_one(struct aiocb *cbs, unsigned int *tail)
{
    struct aiocb *cb = &cbs[*tail & (MAX_CBS - 1)];

    while (aio_error(cb) == EINPROGRESS) {
        const struct aiocb *p = cb;
        aio_suspend(&p, 1, NULL);
    }

    int error = aio_error(cb);
    if (error && error != EINPROGRESS) {
        fprintf(stderr, "aio error on seq %u: %s\n", *tail, strerror(error));
    }

    aio_return(cb);
    (*tail)++;
}

int
main(void)
{
    const char *path = "aio-test.out";
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_APPEND, 0644);
    if (fd < 0) {
        perror("open");
        return 1;
    }

    struct aiocb cbs[MAX_CBS];
    char buffers[MAX_CBS][LINE_LEN + 1];  /* +1 for newline. */
    unsigned int head = 0, tail = 0;
    int i;

    for (i = 0; i < N_WRITES; i++) {
        while (head - tail >= MAX_CBS) {
            drain_one(cbs, &tail);
        }

        unsigned int slot = head & (MAX_CBS - 1);
        char fill = (i % 2) ? 'B' : 'A';

        snprintf(buffers[slot], PREFIX_LEN + 1, "%08d ", i);
        memset(buffers[slot] + PREFIX_LEN, fill, LINE_LEN - PREFIX_LEN);
        buffers[slot][LINE_LEN] = '\n';

        memset(&cbs[slot], 0, sizeof(cbs[slot]));
        cbs[slot].aio_fildes = fd;
        cbs[slot].aio_buf = buffers[slot];
        cbs[slot].aio_nbytes = LINE_LEN + 1;
        cbs[slot].aio_sigevent.sigev_notify = SIGEV_NONE;

        if (aio_write(&cbs[slot]) == -1) {
            if (errno == EAGAIN) {
                drain_one(cbs, &tail);
                if (aio_write(&cbs[slot]) == -1) {
                    perror("aio_write (retry)");
                    goto flush;
                }
            } else {
                perror("aio_write");
                goto flush;
            }
        }

        head++;
    }

flush:
    while (tail < head) {
        drain_one(cbs, &tail);
    }

    close(fd);

    /* Verify. */
    FILE *f = fopen(path, "r");
    if (!f) {
        perror("fopen");
        return 1;
    }

    char buf[LINE_LEN + 2];
    int bad_order = 0, bad_data = 0, total = 0;
    int expected_seq = 0;

    while (fgets(buf, sizeof(buf), f)) {
        total++;
        int len = strlen(buf);
        if (len > 0 && buf[len - 1] == '\n') {
            buf[--len] = '\0';
        }

        if (len != LINE_LEN) {
            bad_data++;
            printf("BAD LENGTH at line %d: expected %d, got %d\n",
                   total, LINE_LEN, len);
            continue;
        }

        /* Parse sequence number. */
        int seq = -1;
        if (sscanf(buf, "%d", &seq) != 1 || seq < 0) {
            bad_data++;
            printf("BAD SEQ at line %d: %.20s...\n", total, buf);
            continue;
        }

        /* Check ordering. */
        if (seq != expected_seq) {
            if (bad_order < 10) {
                printf("REORDERED at line %d: expected seq %d, got %d\n",
                       total, expected_seq, seq);
            }
            bad_order++;
            expected_seq = seq + 1;
        } else {
            expected_seq++;
        }

        /* Check fill character consistency. */
        char expected_fill = (seq % 2) ? 'B' : 'A';
        for (int j = PREFIX_LEN; j < len; j++) {
            if (buf[j] != expected_fill) {
                if (bad_data < 10) {
                    printf("INTERLEAVED at line %d (seq %d), byte %d: "
                           "expected '%c', got '%c'\n",
                           total, seq, j, expected_fill, buf[j]);
                }
                bad_data++;
                break;
            }
        }
    }
    fclose(f);

    printf("%d lines, %d reordered, %d corrupted\n",
           total, bad_order, bad_data);
    return (bad_order || bad_data) ? 1 : 0;
}
