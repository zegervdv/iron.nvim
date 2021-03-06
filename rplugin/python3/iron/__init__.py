# encoding:utf-8
""" iron.nvim (Interactive Repls Over Neovim).

`iron` is a plugin that allows better interactions with interactive repls
using neovim's job-control and terminal.

Currently it keeps track of a single repl instance per filetype.
"""
import logging
import neovim
from iron.repls import available_repls

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

@neovim.plugin
class Iron(object):

    def __init__(self, nvim):
        self.__nvim = nvim
        self.__repl = {}

        debug_path = (
            'iron_debug' in nvim.vars and './.iron_debug.log'
            or nvim.vars.get('iron_debug_path')
        )

        if debug_path is not None:
            fh = logging.FileHandler(debug_path)
            fh.setLevel(logging.DEBUG)
            log.addHandler(fh)


    def get_repl_template(self, ft):
        repls = list(filter(
            lambda k: ft == k['language'] and k['detect'](),
            available_repls))

        log.info('Got {} as repls for {}'.format(
            [i['command'] for i in repls], ft
        ))

        return len(repls) and repls[0] or {}

    # Helper fns
    def termopen(self, cmd):
        return self.__nvim.call('termopen', cmd)

    def get_ft(self):
        return self.__nvim.current.buffer.options["ft"]

    def get_current_repl(self):
        return self.__repl.get(self.get_ft())

    def get_current_bindings(self):
        return self.get_current_repl().get('fns', {})

    def send_data(self, data, repl=None):
        repl = repl or self.get_current_repl()
        log.info('Sending data to repl ({}):\n{}'.format(
            repl['repl_id'], data
        ))

        self.__nvim.call('jobsend', repl["repl_id"], data)

    def set_repl_for_ft(self, ft):
        if ft not in self.__repl:
            self.__repl[ft] = self.get_repl_template(ft)

        return self.__repl[ft]

    def call_cmd(self, cmd):
        return self.__nvim.command(cmd)

    def call(self, cmd, *args):
        return self.__nvim.call(cmd, *args)

    def register(self, reg):
        return self.__nvim.funcs.getreg(reg)

    def set_register(self, reg, data):
        log.info("Setting register '{}' with value '{}'".format(reg, data))
        return self.__nvim.funcs.setreg(reg, data)

    def set_variable(self, var, data):
        log.info("Setting variable '{}' with value '{}'".format(var, data))
        self.__nvim.vars[var] = data

    def prompt(self, msg):
        self.call("inputsave")
        ret = self.call("input", "iron> {}: ".format(msg))
        self.call("inputrestore")
        return ret


    # Actual Fns
    def open_repl_for(self, ft):
        log.info("Opening repl for {}".format(ft))
        repl = self.set_repl_for_ft(ft)

        if not repl:
            msg = "No repl found for {}".format(ft)
            log.info(msg)
            self.call_cmd("echomsg '{}'".format(msg))
            return

        self.call_cmd('spl | wincmd j | enew')

        repl_id = self.termopen(repl['command'])

        # TODO Make optional nvimux integration detached
        self.__nvim.current.buffer.vars['nvimux_buf_orientation'] = (
            "botright split"
        )

        self.__repl[ft]['fns'] = {}
        base_cmd = 'nnoremap <silent> {} :call IronSendSpecial("{}")<CR>'

        for k, n, c in repl.get('mappings', []):
            log.info("Mapping '{}' to function '{}'".format(k, n))

            self.call_cmd(base_cmd.format(k, n))
            self.__repl[ft]['fns'][n] = c

        self.__repl[ft]['repl_id'] = repl_id
        self.set_variable(
            "iron_{}_repl".format(ft), self.__nvim.current.buffer.number
        )

        return repl_id

    def sanitize_multiline(self, data):
        repl = self.__repl.get(self.get_ft())
        if "\n" in data and repl:
            (pre, post) = repl['multiline']
            log.info("Multinine string supplied.")
            return "{}\n{}{}\n".format(pre, data, post)
        log.info("String was not multiline. Continuing")
        return data

    @neovim.command("IronPromptRepl")
    def prompt_query(self):
        self.open_repl_for(self.prompt("repl type"))

    @neovim.command("IronRepl")
    def get_repl(self):
        self.open_repl_for(self.get_ft())

    @neovim.function("IronSendSpecial")
    def mapping_send(self, args):
        fn = self.get_current_bindings().get(args[0])
        if fn:
            fn(self)

    @neovim.function("IronSendMotion")
    def send_motion_to_repl(self, args):
        if args[0] == 'line':
            self.call_cmd("""normal! '[V']"sy""")
        else:
            self.call_cmd("""normal! `[v`]"sy""")

        return self.send_to_repl([self.__nvim.funcs.getreg('s')])

    @neovim.function("IronSend")
    def send_to_repl(self, args):
        repl = self.__repl.get(args[1]) if len(args) > 1 else None
        repl = repl or self.get_current_repl()

        if not repl:
            return None

        log.info("Sending data to repl -> {}".format(repl))

        if 'multiline' in repl:
            log.info("Multiline statement allowed - wrapping")
            data = self.sanitize_multiline(args[0])
        else:
            log.info("Plain string - no multiline")
            data = "{}\r".format(args[0])

        return self.send_data(data, repl)
