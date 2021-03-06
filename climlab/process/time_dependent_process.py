import numpy as np
import copy
from climlab import constants as const
from climlab.process.process import Process
from climlab.utils.walk import walk_processes


class TimeDependentProcess(Process):
    '''A generic parent class for all time-dependent processes.'''
    def __init__(self, time_type='explicit', timestep=None, topdown=True, **kwargs):
        # Create the state dataset
        super(TimeDependentProcess, self).__init__(**kwargs)
        self.tendencies = {}
        self.timeave = {}
        if timestep is None:
            self.set_timestep()
        else:
            self.set_timestep(timestep=timestep)
        self.time_type = time_type
        self.topdown = topdown
        self.has_process_type_list = False

    def set_timestep(self, timestep=const.seconds_per_day, num_steps_per_year=None):
        '''Change the timestep.
        Input is either timestep in seconds,
        or
        num_steps_per_year: a number of steps per calendar year.'''
        if num_steps_per_year is not None:
            timestep = const.seconds_per_year / num_steps_per_year
        else:
            num_steps_per_year = const.seconds_per_year / timestep
        # Need a more sensible approach for annual cycle stuff
        timestep_days = timestep / const.seconds_per_day
        days_of_year = np.arange(0., const.days_per_year, timestep_days)
        self.time = {'timestep': timestep,
                     'num_steps_per_year': num_steps_per_year,
                     'day_of_year_index': 0,
                     'steps': 0,
                     'days_elapsed': 0,
                     'years_elapsed': 0,
                     'days_of_year': days_of_year}
        self.param['timestep'] = timestep

    def compute(self):
        '''By default, the tendency is zero.'''
        for varname in self.state.keys():
            self.tendencies[varname] = np.zeros_like(self.state[varname])

    def _build_process_type_list(self):
        '''Generate lists of processes organized by process type
        Currently, this can be 'diagnostic', 'explicit', 'implicit', or 'adjustment'.'''
        self.process_types = {'diagnostic': [], 'explicit': [], 'implicit': [], 'adjustment': []}        
        for name, proc, level in walk_processes(self, topdown=self.topdown):
            self.process_types[proc.time_type].append(proc)
        self.has_process_type_list = True
        
    def step_forward(self):
        '''new oop climlab... just loop through processes
        and add up the tendencies'''
        if not self.has_process_type_list:
            self._build_process_type_list()
        # First compute all strictly diagnostic processes
        for proc in self.process_types['diagnostic']:
            proc.compute()
        # Compute tendencies and diagnostics for all explicit processes
        for proc in self.process_types['explicit']:
            proc.compute()
        # Update state variables using all explicit tendencies
        #  Tendencies are d/dt(state) -- so just multiply by timestep for forward time
        for proc in self.process_types['explicit']:
            for varname in proc.state.keys():
                try: proc.state[varname] += (proc.tendencies[varname] *
                                             self.param['timestep'])
                except: pass
        # Now compute all implicit processes -- matrix inversions
        for proc in self.process_types['implicit']:
            proc.compute()
            for varname in proc.state.keys():
                try: proc.state[varname] += proc.adjustment[varname]
                except: pass
        # Adjustment processes change the state instantaneously
        for proc in self.process_types['adjustment']:
            proc.compute()
            for varname, value in proc.state.iteritems():
                #proc.set_state(varname, proc.adjusted_state[varname])
                try: proc.state[varname] += proc.adjustment[varname]
                except: pass
        # Gather all diagnostics
        for name, proc, level in walk_processes(self):
            self.diagnostics.update(proc.diagnostics)
            proc._update_time()

    def compute_diagnostics(self, num_iter=3):
        '''Compute all tendencies and diagnostics, but don't update model state.
        By default it will call step_forward() 3 times to make sure all
        subprocess coupling is accounted for. The number of iterations can
        be changed with the input argument.'''
        #  This might create a time problem because it updates the time counter...
        this_state = copy.deepcopy(self.state)
        for n in range(num_iter):
            self.step_forward()
            for name, value in self.state.iteritems():
                self.state[name][:] = this_state[name][:]

    def _update_time(self):
        '''Increment the timestep counter by one.
        This function is called by the timestepping routines.'''
        self.time['steps'] += 1
        # time in days since beginning
        self.time['days_elapsed'] += self.time['timestep'] / const.seconds_per_day
        if self.time['day_of_year_index'] >= self.time['num_steps_per_year']-1:
            self._do_new_calendar_year()
        else:
            self.time['day_of_year_index'] += 1

    def _do_new_calendar_year(self):
        '''This function is called once at the end of every calendar year.'''
        self.time['day_of_year_index'] = 0  # back to Jan. 1
        self.time['years_elapsed'] += 1

    def integrate_years(self, years=1.0, verbose=True):
        '''Timestep the model forward a specified number of years.'''
        days = years * const.days_per_year
        numsteps = int(self.time['num_steps_per_year'] * years)
        if verbose:
            print("Integrating for " + str(numsteps) + " steps, "
                  + str(days) + " days, or " + str(years) + " years.")
        #  begin time loop
        for count in range(numsteps):
            # Compute the timestep
            self.step_forward()
            if count == 0:
                # on first step only...
                #  This implements a generic time-averaging feature
                # using the list of model state variables
                self.timeave = self.state.copy()
                # add any new diagnostics to the timeave dictionary
                self.timeave.update(self.diagnostics)
                for varname, value in self.timeave.iteritems():
                    self.timeave[varname] = np.zeros_like(value)
            for varname in self.timeave.keys():
                try:
                    self.timeave[varname] += self.state[varname]
                except:
                    try:
                        self.timeave[varname] += self.diagnostics[varname]
                    except: pass
        for varname in self.timeave.keys():
            self.timeave[varname] /= numsteps
        if verbose:
            print("Total elapsed time is %s years." 
                  % str(self.time['days_elapsed']/const.days_per_year))

    def integrate_days(self, days=1.0, verbose=True):
        '''Timestep the model forward a specified number of days.'''
        years = days / const.days_per_year
        self.integrate_years(years=years, verbose=verbose)
