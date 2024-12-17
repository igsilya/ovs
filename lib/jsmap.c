/* Copyright (c) 2024 Red Hat, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at:
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License. */

#include <config.h>
#include "openvswitch/jsmap.h"

#include <strings.h>

#include "json.h"
#include "util.h"

static struct jsmap_node *jsmap_add__(struct jsmap *,
                                      const struct json *key,
                                      const struct json *value,
                                      size_t hash);
static struct jsmap_node *jsmap_find__(const struct jsmap *,
                                       const struct json *key,
                                       size_t hash);
static int compare_nodes_by_key(const void *, const void *);

/* Public Functions. */

void
jsmap_init(struct jsmap *jsmap)
{
    hmap_init(&jsmap->map);
}

void
jsmap_destroy(struct jsmap *jsmap, bool yield)
{
    if (jsmap) {
        jsmap_clear(jsmap, yield);
        hmap_destroy(&jsmap->map);
    }
}

/* Adds 'key' paired with 'value' to 'jsmap'.  Clones both the 'key' and the
 * 'value', uses deep clone if 'deep_clone' is true.  It is the caller's
 * responsibility to avoid duplicate keys if desirable. */
struct jsmap_node *
jsmap_add(struct jsmap *jsmap, const struct json *key,
          const struct json *value, bool deep_clone)
{
    key = deep_clone ? json_deep_clone(key) : json_clone(key);
    value = deep_clone ? json_deep_clone(value) : json_clone(value);

    return jsmap_add__(jsmap, key, value, json_hash(key, 0));
}

/* Adds 'key' paired with 'value' to 'jsmap'.  Takes ownership of 'key' and
 * 'value' (both will eventually be destroyed with json_destroy()).  It is the
 * caller's responsibility to avoid duplicate keys if desirable. */
struct jsmap_node *
jsmap_add_noclone(struct jsmap *jsmap, struct json *key, struct json *value)
{
    return jsmap_add__(jsmap, key, value, json_hash(key, 0));
}

/* Attempts to add 'key' to 'jsmap' associated with 'value'.  If 'key' already
 * exists in 'jsmap', does nothing and returns false.  Otherwise, performs the
 * addition and returns true. */
bool
jsmap_add_once(struct jsmap *jsmap,
               const struct json *key, const struct json *value,
               bool deep_clone)
{
    if (!jsmap_get(jsmap, key)) {
        jsmap_add(jsmap, key, value, deep_clone);
        return true;
    } else {
        return false;
    }
}

/* Searches for 'key' in 'jsmap'.  If it does not already exists, adds it,
 * cloning the 'key' and the 'value' (deep clone if 'deep_clone' is true).
 * Otherwise, changes its value to a 'value' (cloned). */
void
jsmap_replace(struct jsmap *jsmap,
              const struct json *key, const struct json *value,
              bool deep_clone)
{
    size_t hash = json_hash(key, 0);
    struct jsmap_node *node;

    value = deep_clone ? json_deep_clone(value) : json_clone(value);

    node = jsmap_find__(jsmap, key, hash);
    if (node) {
        json_destroy(node->value);
        node->value = CONST_CAST(struct json *, value);
    } else {
        key = deep_clone ? json_deep_clone(key) : json_clone(key);
        jsmap_add__(jsmap, key, value, hash);
    }
}

/* If 'key' is in 'jsmap', removes it.  Otherwise does nothing. */
void
jsmap_remove(struct jsmap *jsmap, const struct json *key, bool yield)
{
    struct jsmap_node *node = jsmap_get_node(jsmap, key);

    if (node) {
        jsmap_remove_node(jsmap, node, yield);
    }
}


/* Removes 'node' from 'jsmap'. */
void
jsmap_remove_node(struct jsmap *jsmap, struct jsmap_node *node, bool yield)
{
    hmap_remove(&jsmap->map, &node->node);
    if (yield) {
        json_destroy_with_yield(node->key);
        json_destroy_with_yield(node->value);
    } else {
        json_destroy(node->key);
        json_destroy(node->value);
    }
    free(node);
}

/* Deletes 'node' from 'jsmap'.
 *
 * If 'keyp' is nonnull, stores the node's key in '*keyp' and transfers
 * ownership to the caller.  Otherwise, frees the node's key.  Similarly for
 * 'valuep' and the node's value. */
void
jsmap_steal(struct jsmap *jsmap, struct jsmap_node *node,
            struct json **keyp, struct json **valuep)
{
    if (keyp) {
        *keyp = node->key;
    } else {
        json_destroy(node->key);
    }

    if (valuep) {
        *valuep = node->value;
    } else {
        json_destroy(node->value);
    }

    hmap_remove(&jsmap->map, &node->node);
    free(node);
}

/* Removes all key-value pairs from 'jsmap'. */
void
jsmap_clear(struct jsmap *jsmap, bool yield)
{
    struct jsmap_node *node;

    JSMAP_FOR_EACH_SAFE (node, jsmap) {
        jsmap_remove_node(jsmap, node, yield);
    }
}

/* Returns the value associated with 'key' in 'jsmap'.
 * If 'jsmap' does not contain 'key', returns NULL. */
const struct json *
jsmap_get(const struct jsmap *jsmap, const struct json *key)
{
    struct jsmap_node *node = jsmap_get_node(jsmap, key);
    return node ? node->value : NULL;
}

/* Returns the node associated with 'key' in 'jsmap', or NULL. */
struct jsmap_node *
jsmap_get_node(const struct jsmap *jsmap, const struct json *key)
{
    return jsmap_find__(jsmap, key, json_hash(key, 0));
}

/* Returns true of there are no elements in 'jsmap'. */
bool
jsmap_is_empty(const struct jsmap *jsmap)
{
    ovs_assert(jsmap);
    return hmap_is_empty(&jsmap->map);
}

/* Returns the number of elements in 'jsmap'. */
size_t
jsmap_count(const struct jsmap *jsmap)
{
    ovs_assert(jsmap);
    return hmap_count(&jsmap->map);
}

/* Initializes 'dst' as a clone of 'src. */
void
jsmap_clone(struct jsmap *dst, const struct jsmap *src, bool deep)
{
    const struct json *key, *value;
    const struct jsmap_node *node;

    jsmap_init(dst);
    hmap_reserve(&dst->map, jsmap_count(src));

    JSMAP_FOR_EACH (node, src) {
        key = deep ? json_deep_clone(node->key) : json_clone(node->key);
        value = deep ? json_deep_clone(node->value) : json_clone(node->value);

        jsmap_add__(dst, key, value, node->node.hash);
    }
}

/* Returns an array of nodes sorted on key or NULL if 'jsmap' is empty.  The
 * caller is responsible for freeing this array. */
const struct jsmap_node **
jsmap_sort(const struct jsmap *jsmap)
{
    if (jsmap_is_empty(jsmap)) {
        return NULL;
    } else {
        const struct jsmap_node **nodes;
        struct jsmap_node *node;
        size_t i, n;

        n = jsmap_count(jsmap);
        nodes = xmalloc(n * sizeof *nodes);
        i = 0;
        JSMAP_FOR_EACH (node, jsmap) {
            nodes[i++] = node;
        }
        ovs_assert(i == n);

        qsort(nodes, n, sizeof *nodes, compare_nodes_by_key);

        return nodes;
    }
}

/* Returns true if the two maps are equal, meaning that they have the same set
 * of key-value pairs.
 */
bool
jsmap_equal(const struct jsmap *jsmap1, const struct jsmap *jsmap2)
{
    if (jsmap_count(jsmap1) != jsmap_count(jsmap2)) {
        return false;
    }

    const struct jsmap_node *node;
    JSMAP_FOR_EACH (node, jsmap1) {
        const struct json *value2 = jsmap_get(jsmap2, node->key);

        if (!value2 || !json_equal(node->value, value2)) {
            return false;
        }
    }
    return true;
}

struct json *
jsmap_find_and_delete(struct jsmap *jsmap, const struct json *key)
{
    struct jsmap_node *node = jsmap_get_node(jsmap, key);
    struct json *value;

    if (!node) {
        return NULL;
    }

    value = json_clone(node->value);
    jsmap_remove_node(jsmap, node, false);

    return value;
}

struct jsmap_node *
jsmap_first(const struct jsmap *jsmap)
{
    struct hmap_node *node = hmap_first(&jsmap->map);
    return node ? CONTAINER_OF(node, struct jsmap_node, node) : NULL;
}

/* Private Helpers. */

static struct jsmap_node *
jsmap_add__(struct jsmap *jsmap, const struct json *key,
            const struct json *value, size_t hash)
{
    struct jsmap_node *node = xmalloc(sizeof *node);

    node->key = CONST_CAST(struct json *, key);
    node->value = CONST_CAST(struct json *, value);
    hmap_insert(&jsmap->map, &node->node, hash);

    return node;
}

static struct jsmap_node *
jsmap_find__(const struct jsmap *jsmap, const struct json *key, size_t hash)
{
    struct jsmap_node *node;

    HMAP_FOR_EACH_WITH_HASH (node, node, hash, &jsmap->map) {
        if (json_equal(key, node->key)) {
            return node;
        }
    }

    return NULL;
}

static int
compare_nodes_by_key(const void *a_, const void *b_)
{
    const struct jsmap_node *const *a = a_;
    const struct jsmap_node *const *b = b_;
    const struct json *ja = (*a)->key;
    const struct json *jb = (*b)->key;

    ovs_assert(ja->type == jb->type);

    switch (ja->type) {
    case JSON_STRING:
    case JSON_SERIALIZED_OBJECT:
        return strcmp(json_string(ja), json_string(jb));

    case JSON_INTEGER:
        return json_integer(ja) - json_integer(jb);

    case JSON_REAL:
        return json_real(ja) - json_real(jb);

    case JSON_ARRAY:
    case JSON_OBJECT:
    case JSON_NULL:
    case JSON_FALSE:
    case JSON_TRUE:
        /* Order on these types doesn't make a lot of sense. */
        OVS_NOT_REACHED();

    case JSON_N_TYPES:
    default:
        OVS_NOT_REACHED();
    }
    return 0;
}
