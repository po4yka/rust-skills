// The C interface of the tally library. The iOS app imports it through a bridging header.
#ifndef TALLY_H
#define TALLY_H

#include <stdint.h>

typedef struct Tally Tally;

// Creates a tally. `name` is a NUL-terminated UTF-8 string.
Tally *tally_new(const char *name);

// Adds `n` and returns the new count.
uint64_t tally_add(Tally *tally, uint64_t n);

// Returns the name of the tally.
const char *tally_name(const Tally *tally);

// Frees a tally.
void tally_free(Tally *tally);

#endif
