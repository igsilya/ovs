#!/bin/bash

# Notes:
#
# - This script clones and works with ovs repository in /tmp.
#   So, /tmp/ovs will be removed by 'make-patches' command and re-created.
#
# - All stable branches should be previously correctly tagged since this
#   script will find the last tag on each branch and create release patches and
#   new tags for version 'last_tag + 1'.
#
# - By default this script will try to use $(pwd) as a reference to speed up
#   clone of the repository.  So, it's better to run from the top of the
#   existing openvswitch repository.  Alternatively, 'GIT_REFERENCE'
#   environment variable could be used.
#
# - Also this script will add all remotes, except origin, of the current git
#   tree to the new git tree in /tmp/ovs, so they could be used later for
#   'push-releases' command.  Might be useful for testing purposes before
#   pushing to origin.

set -x
set -o errexit

prepare_patches_for_minor_release()
{
    LAST_VERSION=$(git describe --abbrev=0 | cut -c 2-)

    if [ -z "$LAST_VERSION" ] ; then
        echo "Could not parse version.  Assuming major release."
        BRANCH=$(git rev-parse --abbrev-ref HEAD \
                 | sed 's/[a-z-]*\([0-9\.]*\)/\1/')
        LAST_VERSION="${BRANCH}.-1"
        MAJOR=yes
    fi

    BRANCH=${LAST_VERSION%.*}
    RELEASE=${LAST_VERSION##*.}
    VERSION=${BRANCH}.$(($RELEASE + 1))
    NEXT_VERSION=${BRANCH}.$(($RELEASE + 2))

    echo "Preparing patches for version ${VERSION}"

    DATE=$(date +'%d %b %Y')
    DATETIME=$(date -R)

    echo "Creating release date adjustment commit"

    sed -i "1 s/xx xxx xxxx/${DATE}/" NEWS
    [ -n "$MAJOR" ] || sed -i "3 i \   - Bug fixes" NEWS

    sed -i "5 c \ -- Open vSwitch team <dev@openvswitch.org>  ${DATETIME}" \
           debian/changelog

    # Last-minute NEWS update.
    vim NEWS

    git commit -a -s -m "Set release date for ${VERSION}."

    echo "Creating next release preparation commit"

    VERSION_LINE="v${NEXT_VERSION} - xx xxx xxxx"
    printf -v DASH_LINE '%0.s-' $(seq 1 ${#VERSION_LINE})
    sed -i "1 i ${VERSION_LINE}\n${DASH_LINE}\n" NEWS

    sed -i "1 i openvswitch (${NEXT_VERSION}-1) unstable; urgency=low\n" \
                                                  debian/changelog
    sed -i "2 i \   [ Open vSwitch team ]"        debian/changelog
    sed -i "3 i \   * New upstream version\n"     debian/changelog
    sed -i "5 i \ -- Open vSwitch team <dev@openvswitch.org>  ${DATETIME}" \
                                                  debian/changelog

    sed -i \
      "s/AC_INIT(openvswitch, ${VERSION}/AC_INIT(openvswitch, ${NEXT_VERSION}/"\
      configure.ac

    git commit -a -s -m "Prepare for ${NEXT_VERSION}."

    echo "Formatting patches for email"
    mkdir -p patches/release-${VERSION}
    git format-patch -o patches/release-${VERSION}             \
                     --subject-prefix="PATCH branch-${BRANCH}" \
                     --cover-letter -2
    sed -i "s/\*\*\* SUBJECT HERE \*\*\*/Release patches for v${VERSION}./" \
        patches/release-${VERSION}/0000-cover-letter.patch
    sed -i "/\*\*\* BLURB HERE \*\*\*/d" \
        patches/release-${VERSION}/0000-cover-letter.patch
}

clone_and_set_remotes()
{
    rm -rf /tmp/ovs
    git clone --reference-if-able ${GIT_REFERENCE} --dissociate \
              https://github.com/openvswitch/ovs.git
    pushd ovs

    if [ -n "${remotes}" ]; then
        echo "${remotes}" | while read line ; do
            git remote add ${line}
        done
    fi
    popd
}

usage()
{
    set +x
    echo "Usage: ${0} command BRANCHES [extra-options]"
    echo "Commands:"
    echo "  make-patches   BRANCHES                 (create patch files)"
    echo "  send-emails    BRANCHES [extra options] (send patches)"
    echo "  add-commit-tag BRANCHES TAG             (add commit message tag)"
    echo "  tag-releases   BRANCHES                 (add git tags to commits)"
    echo "  push-releases  BRANCHES remote [extra]  (push to github)"
    echo "  update-website all                      (prepare website commit)"
    echo "  announce       BRANCHES [extra options] (send announce email)"
    echo
    echo "Ex.:"
    echo "  $ ${0} make-patches   '2.7 2.8' "
    echo "  $ ${0} send-emails    '2.7 2.8' --cc \"Name <email>\" --dry-run"
    echo "  $ ${0} add-commit-tag '2.7 2.8' 'Acked-by: Name <email>'"
    echo "  $ ${0} tag-releases   '2.7 2.8'"
    echo "  $ ${0} push-releases  '2.7 2.8' origin --dry-run"
    echo "  $ ${0} update-website  all"
    echo "  $ ${0} announce       '2.7 2.8' --cc \"Name <email>\" --dry-run"
}

[ "$#" -gt 1 ] || (usage && exit 1)

command=${1}
shift
BRANCHES="${1}"
shift

GIT_REFERENCE=${GIT_REFERENCE:-$(pwd)}

remotes=""
if git rev-parse --git-dir > /dev/null 2>&1; then
    remotes=$(git remote -v | grep fetch | grep -v origin | sed 's/ (.*)//')
fi

pushd /tmp

case $command in
make-patches)
    clone_and_set_remotes
    pushd ovs
    for BR in ${BRANCHES}; do
        git checkout origin/branch-${BR} -b release-branch-${BR}
        git pull --rebase
        prepare_patches_for_minor_release
    done
    popd
    ;;
send-emails)
    pushd ovs
    git checkout master
    for BR in ${BRANCHES}; do
        ./utilities/checkpatch.py patches/release-${BR}*/*
        git send-email --to 'ovs-dev@openvswitch.org' "${@}" \
                       patches/release-${BR}*/*
    done
    popd
    ;;
add-commit-tag)
    pushd ovs
    git reset --hard
    for BR in ${BRANCHES}; do
        sed -i "/Signed-off-by.*/i ${@}" patches/release-${BR}*/000[1-2]*
        git checkout release-branch-${BR}
        git reset --hard HEAD~2
        git am patches/release-${BR}*/000[1-2]*
        git pull --rebase
    done
    popd
    ;;
tag-releases)
    pushd ovs
    for BR in ${BRANCHES}; do
        git checkout release-branch-${BR}
        git pull --rebase
        version=$(git log HEAD^ -1 --pretty="%s" | \
                  sed 's/.* \([0-9]*\.[0-9]*\.[0-9]*\)\./\1/')
        git tag -s v${version} -m "Open vSwitch version ${version}." HEAD^
    done
    popd
    ;;
push-releases)
    pushd ovs
    for BR in ${BRANCHES}; do
        git checkout release-branch-${BR}
        git push "${@}" HEAD:branch-${BR} --follow-tags
    done
    popd
    ;;
update-website)
    rm -rf /tmp/openvswitch.github.io
    git clone https://github.com/openvswitch/openvswitch.github.io.git

    pushd ovs
    git fetch
    git tag | grep -E 'v[2-9]\.[0-9]*\.[0-9]*$' | cut -c 2- | sort -V -r | \
              sed '/2.5.0/q' | sed -e 's/^/- /' \
              >> ../openvswitch.github.io/_data/releases.yml
    popd

    pushd openvswitch.github.io
    sort -V -u -r _data/releases.yml -o _data/releases.yml
    missed_versions=$(git diff | grep '^+- ' | cut -c 4- | tac)
    popd

    pushd ovs
    for version in ${missed_versions}; do
        git reset --hard
        git checkout v${version}
        ./boot.sh && ./configure && make dist-gzip
        make distclean
        cp openvswitch-${version}* ../openvswitch.github.io/releases/
        cp NEWS ../openvswitch.github.io/releases/NEWS-${version}
        cp NEWS ../openvswitch.github.io/releases/NEWS-${version}.txt
    done

    latest=$(git tag | sort -V -r | head -1 | cut -c 2-)
    latest_lts=$(git tag | grep "v2\.13\." | sort -V -r | head -1 | cut -c 2-)
    popd

    pushd openvswitch.github.io
    sed -i "/Current release/{s/[0-9]*\.[0-9]*\.[0-9]*/${latest}/g}" \
           _includes/side-widgets.html
    sed -i "/Current LTS/{s/[0-9]*\.[0-9]*\.[0-9]*/${latest_lts}/g}" \
           _includes/side-widgets.html

    sed -i "/The most recent.*current/{n;s/-[0-9\.]*.tar/-${latest}.tar/g}" \
           download/index.html
    sed -i "/The most recent.*LTS/{n;s/-[0-9\.]*.tar/-${latest_lts}.tar/g}" \
           download/index.html

    git add releases/*
    releases=$(echo "${missed_versions}" | tac | head -4 | tr '\n' ' ')
    all_releases=$(echo "${missed_versions}" | sed -e 's/^/  - /')
    git commit -s -a -m "Add new and missing releases: ${releases} etc." \
                     -m "Added tarballs and NEWS for:" -m "${all_releases}"
    popd
    ;;
announce)
    pushd ovs
    subject=""
    echo "From: $(git config user.name) <$(git config user.email)>" > mbox
    echo "" >> mbox
    echo "The Open vSwitch team is pleased to announce a number" \
         "of bug fix releases:" >> mbox
    echo "" >> mbox

    BRANCHES=$(echo $BRANCHES | tr ' ' '\n' | tac | tr '\n' ' ')
    for BR in ${BRANCHES}; do
        git reset --hard
        git checkout release-branch-${BR}
        git pull --rebase
        tag=$(git describe --abbrev=0 | cut -c 2-)
        subject="${subject}, ${tag}"
        archive="openvswitch-${tag}.tar.gz"
        echo "  https://www.openvswitch.org/releases/${archive}" >> mbox
    done
    echo "" >> mbox
    echo "--The Open vSwitch Team" >> mbox
    echo "" >> mbox
    echo "--------------------"
    echo "Open vSwitch is a production quality, multilayer open source"      \
         "virtual switch. It is designed to enable massive network"          \
         "automation through programmatic extension, while still supporting" \
         "standard management interfaces. Open vSwitch can operate both as"  \
         "a soft switch running within the hypervisor, and as the control"   \
         "stack for switching silicon. It has been ported to multiple"       \
         "virtualization platforms and switching chipsets."                  \
           | fold -sw 78 >> mbox

    subject=$(echo "$subject" | sed 's/^,\(.*\)/\1/' | sed 's/\(.*\),/\1 and/')
    sed -i "2 i Subject:${subject} Available.\n" mbox
    git send-email --to 'ovs-announce@openvswitch.org' mbox "${@}"
    rm -rf mbox
    popd
    ;;
*)
    usage
    ;;
esac
