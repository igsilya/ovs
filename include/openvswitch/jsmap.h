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
 * limitations under the License.  */

#ifndef JSMAP_H
#define JSMAP_H 1

#include "openvswitch/hmap.h"

#ifdef __cplusplus
extern "C" {
#endif

struct json;

/* A map from json to json. */
struct jsmap {
    struct hmap map;           /* Contains "struct jsmap_node"s. */
};

struct jsmap_node {
    struct hmap_node node;     /* In struct jsmap's 'map' hmap. */
    struct json *key;
    struct json *value;
};

#define JSMAP_INITIALIZER(JSMAP) { HMAP_INITIALIZER(&(JSMAP)->map) }

#define JSMAP_FOR_EACH(JSMAP_NODE, JSMAP)                                   \
    HMAP_FOR_EACH_INIT (JSMAP_NODE, node, &(JSMAP)->map,                    \
                        BUILD_ASSERT_TYPE(JSMAP_NODE, struct jsmap_node *), \
                        BUILD_ASSERT_TYPE(JSMAP, struct jsmap *))

#define JSMAP_FOR_EACH_SAFE(JSMAP_NODE, JSMAP)                \
    HMAP_FOR_EACH_SAFE_SHORT_INIT (                           \
        JSMAP_NODE, node, &(JSMAP)->map,                      \
        BUILD_ASSERT_TYPE(JSMAP_NODE, struct jsmap_node *),   \
        BUILD_ASSERT_TYPE(JSMAP, struct jsmap *))

#define JSMAP_NODE(KEY, VALUE, NEXT)                   \
        &(struct jsmap_node) {                         \
            .node = {                                  \
                .hash = json_hash(KEY, 0),             \
                .next = (NEXT),                        \
            },                                         \
            .key = CONST_CAST(struct json *, KEY),     \
            .value = CONST_CAST(struct json *, VALUE), \
        }.node

void jsmap_init(struct jsmap *);
void jsmap_destroy(struct jsmap *, bool yield);

struct jsmap_node *jsmap_add(struct jsmap *, const struct json *key,
                             const struct json *value, bool deep_clone);
struct jsmap_node *jsmap_add_noclone(struct jsmap *,
                                     struct json *key, struct json *value);
bool jsmap_add_once(struct jsmap *,
                    const struct json *key, const struct json *value,
                    bool deep_clone);

void jsmap_replace(struct jsmap *,
                   const struct json *key, const struct json *value,
                   bool deep_clone);
void jsmap_remove(struct jsmap *, const struct json *, bool yield);
void jsmap_remove_node(struct jsmap *, struct jsmap_node *, bool yield);
void jsmap_steal(struct jsmap *, struct jsmap_node *node,
                 struct json **keyp, struct json **valuep);
void jsmap_clear(struct jsmap *, bool yield);

const struct json *jsmap_get(const struct jsmap *, const struct json *);
struct jsmap_node *jsmap_get_node(const struct jsmap *, const struct json *);

bool jsmap_is_empty(const struct jsmap *);
size_t jsmap_count(const struct jsmap *);

void jsmap_clone(struct jsmap *dst, const struct jsmap *src, bool deep);
const struct jsmap_node **jsmap_sort(const struct jsmap *);
bool jsmap_equal(const struct jsmap *, const struct jsmap *);
struct json *jsmap_find_and_delete(struct jsmap *, const struct json *);
struct jsmap_node *jsmap_first(const struct jsmap *);

#ifdef __cplusplus
}
#endif

#endif /* jsmap.h */
